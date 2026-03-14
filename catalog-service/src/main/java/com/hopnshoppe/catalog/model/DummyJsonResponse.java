package com.hopnshoppe.catalog.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;

/**
 * Top-level wrapper for the DummyJSON {@code GET /products} response.
 * <p>Example shape:
 * <pre>
 * {
 *   "products": [ {...}, {...} ],
 *   "total": 194,
 *   "skip": 0,
 *   "limit": 30
 * }
 * </pre>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class DummyJsonResponse {

    private List<DummyJsonProduct> products;
    private int total;
    private int skip;
    private int limit;
}
