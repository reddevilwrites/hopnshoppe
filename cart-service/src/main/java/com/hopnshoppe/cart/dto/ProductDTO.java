package com.hopnshoppe.cart.dto;

/**
 * Mirrors the ProductDTO returned by catalog-service.
 * Used to deserialize the catalog-service REST response.
 */
public class ProductDTO {
    public String title;
    public String sku;
    public String description;
    public double price;
    public boolean availability;
    public String category;
    public String imagePath;
}
