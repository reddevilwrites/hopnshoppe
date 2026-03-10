package com.hopnshoppe.cart.client;

import com.hopnshoppe.cart.dto.ProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

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
}
