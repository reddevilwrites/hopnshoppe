package com.hopnshoppe.catalog.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

/**
 * Represents a single product from the DummyJSON API response.
 * Unknown fields from the DummyJSON payload are silently ignored.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class DummyJsonProduct {

    private int id;
    private String title;
    private String description;
    private double price;
    /** Primary product thumbnail URL provided by DummyJSON. */
    private String thumbnail;
    private String category;
}
