package com.hopnshoppe.catalog.client;

import com.hopnshoppe.catalog.model.DummyJsonProduct;
import com.hopnshoppe.catalog.model.DummyJsonResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/**
 * Feign client for the DummyJSON external marketplace API.
 *
 * <p>The base URL defaults to {@code https://dummyjson.com} and can be overridden
 * via {@code dummyjson.base-url} in application.yml or the config-server.
 *
 * <p>All calls are wrapped with a Resilience4j circuit breaker in
 * {@link com.hopnshoppe.catalog.service.DummyJsonService} — this interface is
 * intentionally kept free of resilience logic.
 */
@FeignClient(name = "dummyjson", url = "${dummyjson.base-url:https://dummyjson.com}")
public interface DummyJsonClient {

    /**
     * Fetches the default product listing (first page, ~30 items).
     */
    @GetMapping("/products")
    DummyJsonResponse getProducts();

    /**
     * Fetches a single product by its numeric ID.
     */
    @GetMapping("/products/{id}")
    DummyJsonProduct getProductById(@PathVariable int id);
}
