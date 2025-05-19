package com.wknd.spring.client.config_client.service;

import java.util.Collections;
import java.util.List;
import java.util.stream.Collector;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.wknd.spring.client.config_client.model.Product;
import com.wknd.spring.client.config_client.model.ProductDTO;
import com.wknd.spring.client.config_client.model.ProductResponseWrapper;

@Service
public class ProductService {
    private static final String GRAPHQL_QUERY = """
            query {
            productList {
                items {
                title
                sku
                description{
                    plaintext
                }
                price
                availability 
                category
                imagePath
                }
            }
            }
            """;
    
    @Value("${graphql.endpoint}")
    private String endpoint;
    // private static final String ENDPOINT = "http://host.docker.internal:8080/content/cq:graphql/wknd/endpoint.json";
    // private static final String PERSISTED_QUERY_ENDPOINT = "http://host.docker.internal:8080/graphql/execute.json/wknd/sb_client_query";
    private static final Logger logger = LoggerFactory.getLogger(ProductService.class);


    public List<ProductDTO> fetchFilteredProducts(String category, Boolean availability){

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
                filterBuilder.append("availability: {_expressions: { value:  ").append(availability).append("}}");
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
        RestTemplate restTemplate = new RestTemplate();
        HttpHeaders headers = new HttpHeaders();

        headers.setContentType(MediaType.APPLICATION_JSON);

        String body = "{\"query\":\"" + graphqlQuery.replace("\"", "\\\"").replace("\n", "") + "\"}";
        logger.info("GraphQL POST body: {}", body);

        HttpEntity<String> request = new HttpEntity<>(body, headers);

        //Request object for Persisted Query
        // HttpEntity<String> request = new HttpEntity<>("{}", headers);

        try {
            ResponseEntity<ProductResponseWrapper> response = restTemplate.exchange(
                endpoint,
                HttpMethod.POST,
                request,
                ProductResponseWrapper.class
            );
            
            //request to fetch data from persistent endpoint
            // ResponseEntity<ProductResponseWrapper> response = restTemplate.exchange(
            //     PERSISTED_QUERY_ENDPOINT,
            //     HttpMethod.GET,
            //     request,
            //     ProductResponseWrapper.class
            // );

            logger.info("Received response status: {}", response.getStatusCode());
            logger.debug("Response body: {}", response.getBody());
            logger.debug("items inside the response data: {}\nproductList: {}\nitems: {}", response.getBody().data, response.getBody().data.productList, response.getBody().data.productList.items);

            List<Product> products = response.getBody().data.productList.items;

            return products.stream().map(p -> {
                ProductDTO dto = new ProductDTO();
                dto.title = p.title;
                dto.sku = p.sku;
                dto.description = p.description.plaintext;
                dto.price = p.price;
                dto.availability = p.availability;
                dto.category = p.category;
                dto.imagePath = p.imagePath;
                return dto;
            }).collect(Collectors.toList());

            } catch (Exception ex) {
                logger.error("Error while calling GraphQL endpoint", ex);
                return Collections.emptyList(); // or throw custom exception
            }
        }


    public ProductDTO fetchProductBySku(String sku) {
       List<ProductDTO> all = fetchFilteredProducts(null, null);
       return all.stream()
                .filter(p -> p.sku.equals(sku))
                .findFirst()
                .orElse(null);
    }
}
