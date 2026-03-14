package com.hopnshoppe.catalog.service;

import com.hopnshoppe.catalog.client.DummyJsonClient;
import com.hopnshoppe.catalog.model.DummyJsonProduct;
import com.hopnshoppe.catalog.model.ProductDTO;
import com.hopnshoppe.catalog.provider.AemCatalogProvider;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Handles product lookups for the legacy AEM-specific endpoints and the
 * unified single-item / batch endpoints used by cart-service for enrichment.
 *
 * <p>Full catalog aggregation (all providers in parallel) is delegated to
 * {@link CatalogOrchestrator}. This service focuses on targeted lookups:
 * <ul>
 *   <li>Filtered AEM product lists (category, availability)</li>
 *   <li>Single unified product by ID (AEM first, then DummyJSON fallback)</li>
 *   <li>Batch unified product lookup by a list of IDs</li>
 * </ul>
 */
@Service
public class ProductService {

    private static final Logger logger = LoggerFactory.getLogger(ProductService.class);

    private final AemCatalogProvider aemCatalogProvider;
    private final DummyJsonClient dummyJsonClient;

    public ProductService(AemCatalogProvider aemCatalogProvider, DummyJsonClient dummyJsonClient) {
        this.aemCatalogProvider = aemCatalogProvider;
        this.dummyJsonClient = dummyJsonClient;
    }

    // -------------------------------------------------------------------------
    // AEM GraphQL — filtered product listing (legacy endpoint)
    // -------------------------------------------------------------------------

    public List<ProductDTO> fetchFilteredProducts(String category, Boolean availability) {
        return aemCatalogProvider.fetchFiltered(category, availability);
    }

    public ProductDTO fetchProductBySku(String sku) {
        return fetchFilteredProducts(null, null).stream()
                .filter(p -> sku.equals(p.sku))
                .findFirst()
                .orElse(null);
    }

    // -------------------------------------------------------------------------
    // Unified lookups — used by cart-service product enrichment
    // -------------------------------------------------------------------------

    /**
     * Looks up a single product by ID from either AEM or MARKETPLACE.
     *
     * <p>AEM is tried first. If not found and the ID is numeric, DummyJSON is queried.
     * Returns {@code null} if the product is not found in either source.
     */
    public UnifiedProductDTO fetchUnifiedProductById(String id) {
        ProductDTO aemProduct = fetchProductBySku(id);
        if (aemProduct != null) {
            return mapAemToUnified(aemProduct);
        }
        try {
            int numericId = Integer.parseInt(id);
            DummyJsonProduct p = dummyJsonClient.getProductById(numericId);
            if (p != null) {
                return mapDummyJsonToUnified(p);
            }
        } catch (NumberFormatException ignored) {
            // Not a numeric ID — not a MARKETPLACE product
        }
        return null;
    }

    /**
     * Batch lookup for a list of product IDs from either AEM or MARKETPLACE.
     *
     * <p>AEM products are resolved with a single GraphQL call (indexed in memory by SKU).
     * Numeric IDs are treated as MARKETPLACE and fetched from DummyJSON in parallel.
     * IDs not found in either source are silently omitted.
     */
    public List<UnifiedProductDTO> fetchUnifiedProductsByIds(List<String> ids) {
        if (ids == null || ids.isEmpty()) return Collections.emptyList();

        // Single AEM GraphQL call — index by SKU for O(1) lookups
        Map<String, ProductDTO> aemBySku = fetchFilteredProducts(null, null).stream()
                .collect(Collectors.toMap(p -> p.sku, p -> p));

        // Kick off parallel DummyJSON fetches for numeric IDs
        List<CompletableFuture<UnifiedProductDTO>> marketplaceFutures = ids.stream()
                .filter(id -> { try { Integer.parseInt(id); return true; } catch (NumberFormatException e) { return false; } })
                .map(id -> CompletableFuture.supplyAsync(() -> {
                    try {
                        DummyJsonProduct p = dummyJsonClient.getProductById(Integer.parseInt(id));
                        return p != null ? mapDummyJsonToUnified(p) : null;
                    } catch (Exception e) {
                        logger.warn("DummyJSON fetch failed for id {}: {}", id, e.getMessage());
                        return null;
                    }
                }))
                .collect(Collectors.toList());

        List<UnifiedProductDTO> result = new ArrayList<>();
        for (String id : ids) {
            if (aemBySku.containsKey(id)) {
                result.add(mapAemToUnified(aemBySku.get(id)));
            }
        }
        for (CompletableFuture<UnifiedProductDTO> future : marketplaceFutures) {
            try {
                UnifiedProductDTO p = future.join();
                if (p != null) result.add(p);
            } catch (Exception e) {
                logger.warn("DummyJSON batch fetch failed for one item. Cause: {}", e.getMessage());
            }
        }
        return result;
    }

    // -------------------------------------------------------------------------
    // Mapping helpers
    // -------------------------------------------------------------------------

    private UnifiedProductDTO mapAemToUnified(ProductDTO dto) {
        return UnifiedProductDTO.builder()
                .id(dto.sku)
                .name(dto.title)
                .description(dto.description)
                .price(dto.price)
                .imageUrl(dto.imagePath)
                .source("AEM")
                .build();
    }

    private UnifiedProductDTO mapDummyJsonToUnified(DummyJsonProduct p) {
        return UnifiedProductDTO.builder()
                .id(String.valueOf(p.getId()))
                .name(p.getTitle())
                .description(p.getDescription())
                .price(p.getPrice())
                .imageUrl(p.getThumbnail())
                .source("MARKETPLACE")
                .build();
    }
}
