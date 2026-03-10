package com.hopnshoppe.catalog.service;

import com.hopnshoppe.catalog.model.Product;
import com.hopnshoppe.catalog.model.ProductDTO;
import com.hopnshoppe.catalog.model.ProductResponseWrapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class ProductService {

    private static final Logger logger = LoggerFactory.getLogger(ProductService.class);

    @Value("${graphql.endpoint}")
    private String endpoint;

    private final RestTemplate restTemplate = new RestTemplate();

    public List<ProductDTO> fetchFilteredProducts(String category, Boolean availability) {
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
        logger.debug("GraphQL POST body: {}", body);

        HttpEntity<String> request = new HttpEntity<>(body, headers);

        try {
            ResponseEntity<ProductResponseWrapper> response = restTemplate.exchange(
                    endpoint, HttpMethod.POST, request, ProductResponseWrapper.class);

            logger.debug("GraphQL response status: {}", response.getStatusCode());
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

        } catch (Exception ex) {
            logger.error("Error calling GraphQL endpoint {}: {}", endpoint, ex.getMessage());
            return Collections.emptyList();
        }
    }

    public ProductDTO fetchProductBySku(String sku) {
        return fetchFilteredProducts(null, null).stream()
                .filter(p -> sku.equals(p.sku))
                .findFirst()
                .orElse(null);
    }
}
