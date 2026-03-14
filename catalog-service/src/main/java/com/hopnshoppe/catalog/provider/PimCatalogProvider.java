package com.hopnshoppe.catalog.provider;

import com.hopnshoppe.catalog.client.DummyJsonClient;
import com.hopnshoppe.catalog.model.DummyJsonProduct;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

/**
 * {@link CatalogProvider} implementation that fetches products from the DummyJSON
 * REST API, representing the external PIM (Product Information Management) system.
 *
 * <p>Uses the Feign {@link DummyJsonClient} for the HTTP call. Failures are caught
 * and logged; an empty list is returned so the orchestrator can still serve
 * products from other providers.
 */
@Component
public class PimCatalogProvider implements CatalogProvider {

    private static final Logger logger = LoggerFactory.getLogger(PimCatalogProvider.class);

    private final DummyJsonClient dummyJsonClient;

    public PimCatalogProvider(DummyJsonClient dummyJsonClient) {
        this.dummyJsonClient = dummyJsonClient;
    }

    @Override
    public String providerName() {
        return "PIM";
    }

    @Override
    public List<UnifiedProductDTO> fetchProducts() {
        try {
            List<DummyJsonProduct> products = dummyJsonClient.getProducts().getProducts();
            logger.debug("PIM provider returned {} products", products.size());
            return products.stream()
                    .map(p -> UnifiedProductDTO.builder()
                            .id(String.valueOf(p.getId()))
                            .name(p.getTitle())
                            .description(p.getDescription())
                            .price(p.getPrice())
                            .imageUrl(p.getThumbnail())
                            .source("MARKETPLACE")
                            .build())
                    .collect(Collectors.toList());
        } catch (Exception e) {
            logger.error("PIM provider failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }
}
