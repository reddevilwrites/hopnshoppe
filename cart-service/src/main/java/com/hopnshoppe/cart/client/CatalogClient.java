package com.hopnshoppe.cart.client;

import com.hopnshoppe.cart.dto.ProductDTO;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * REST client for catalog-service product lookups.
 *
 * <p>Uses a plain {@link RestTemplate} with a direct URL instead of Feign so that
 * cart-service does not need OpenFeign on its classpath. The URL defaults to the
 * Docker Compose service name and can be overridden via {@code CATALOG_SERVICE_URL}.
 *
 * <p>Returns {@code null} on any failure so callers can gracefully degrade
 * (return a cart item without product metadata rather than failing the whole request).
 */
@Component
public class CatalogClient {

    private static final Logger logger = LoggerFactory.getLogger(CatalogClient.class);

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${catalog.service.url}")
    private String catalogServiceUrl;

    public ProductDTO getProductBySku(String sku) {
        try {
            return restTemplate.getForObject(
                    catalogServiceUrl + "/products/" + sku,
                    ProductDTO.class);
        } catch (Exception e) {
            logger.warn("Failed to fetch product {} from catalog-service: {}", sku, e.getMessage());
            return null;
        }
    }

    /**
     * Fetches a product by ID from the unified endpoint, which resolves from either
     * AEM or MARKETPLACE. Returns {@code null} on 404 or any network failure.
     */
    public UnifiedProductDTO getUnifiedProductById(String id) {
        try {
            return restTemplate.getForObject(
                    catalogServiceUrl + "/products/unified/" + id,
                    UnifiedProductDTO.class);
        } catch (Exception e) {
            logger.warn("Failed to fetch unified product {} from catalog-service: {}", id, e.getMessage());
            return null;
        }
    }

    /**
     * Batch-fetches multiple products by ID in a single HTTP call.
     * Replaces N individual calls in cart enrichment, reducing latency from O(N) to O(1).
     * Returns an empty list on any network failure so callers can degrade gracefully.
     */
    public List<UnifiedProductDTO> getUnifiedProductsByIds(List<String> ids) {
        if (ids == null || ids.isEmpty()) return Collections.emptyList();
        try {
            String idsParam = String.join(",", ids);
            UnifiedProductDTO[] products = restTemplate.getForObject(
                    catalogServiceUrl + "/products/unified/batch?ids=" + idsParam,
                    UnifiedProductDTO[].class);
            return products != null ? Arrays.asList(products) : Collections.emptyList();
        } catch (Exception e) {
            logger.warn("Failed to batch-fetch products from catalog-service: {}", e.getMessage());
            return Collections.emptyList();
        }
    }
}
