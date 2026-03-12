package com.hopnshoppe.catalog.provider;

import com.hopnshoppe.catalog.model.Product;
import com.hopnshoppe.catalog.model.ProductDTO;
import com.hopnshoppe.catalog.model.ProductResponseWrapper;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

/**
 * {@link CatalogProvider} implementation that fetches products from AEM via GraphQL.
 *
 * <p>Also exposes {@link #fetchFiltered(String, Boolean)} for the legacy filtered
 * endpoint in {@code ProductService}, returning raw {@link ProductDTO} objects so
 * the controller can still serve AEM-specific fields (category, availability, etc.).
 */
@Component
public class AemCatalogProvider implements CatalogProvider {

    private static final Logger logger = LoggerFactory.getLogger(AemCatalogProvider.class);

    @Value("${graphql.endpoint}")
    private String endpoint;

    private final RestTemplate restTemplate = new RestTemplate();

    @Override
    public String providerName() {
        return "AEM";
    }

    /**
     * Fetches all AEM products (no filter) and maps them to {@link UnifiedProductDTO}.
     */
    @Override
    public List<UnifiedProductDTO> fetchProducts() {
        return fetchFiltered(null, null).stream()
                .map(p -> UnifiedProductDTO.builder()
                        .id(p.sku)
                        .name(p.title)
                        .description(p.description)
                        .price(p.price)
                        .imageUrl(p.imagePath)
                        .source("AEM")
                        .build())
                .collect(Collectors.toList());
    }

    /**
     * Fetches AEM products with optional category and availability filters.
     * Returns raw {@link ProductDTO} objects for callers that need AEM-specific fields.
     */
    public List<ProductDTO> fetchFiltered(String category, Boolean availability) {
        StringBuilder filterBuilder = new StringBuilder();

        if (category != null || availability != null) {
            filterBuilder.append("(filter: {");
            if (category != null) {
                filterBuilder.append("category: {_expressions: { value: \"").append(category).append("\"}}");
            }
            if (category != null && availability != null) {
                filterBuilder.append(", ");
            }
            if (availability != null) {
                filterBuilder.append("availability: {_expressions: { value: ").append(availability).append("}}");
            }
            filterBuilder.append("})");
        }

        String graphqlQuery = String.format("""
                {
                  productList %s {
                    items {
                      title
                      sku
                      description { plaintext }
                      price
                      availability
                      category
                      imagePath
                    }
                  }
                }
                """, filterBuilder.toString());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        String body = "{\"query\":\"" + graphqlQuery.replace("\"", "\\\"").replace("\n", "") + "\"}";
        logger.debug("AEM GraphQL body: {}", body);

        HttpEntity<String> request = new HttpEntity<>(body, headers);
        try {
            ResponseEntity<ProductResponseWrapper> response = restTemplate.exchange(
                    endpoint, HttpMethod.POST, request, ProductResponseWrapper.class);
            logger.debug("AEM GraphQL status: {}", response.getStatusCode());
            List<Product> products = response.getBody().data.productList.items;
            return products.stream().map(p -> {
                ProductDTO dto = new ProductDTO();
                dto.title = p.title;
                dto.sku = p.sku;
                dto.description = p.description != null ? p.description.plaintext : null;
                dto.price = p.price;
                dto.availability = p.availability;
                dto.category = p.category;
                dto.imagePath = p.imagePath;
                return dto;
            }).collect(Collectors.toList());
        } catch (Exception e) {
            logger.error("AEM GraphQL call failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }
}
