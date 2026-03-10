package com.hopnshoppe.cart.dto;

import lombok.Data;

/**
 * Cart item DTO returned to the frontend.
 * Combines cart state (sku, quantity) with product enrichment from catalog-service.
 */
@Data
public class CartItemDTO {
    private String sku;
    private int quantity;
    private String title;
    private Double price;
    private String imagePath;
    private Boolean availability;
}
