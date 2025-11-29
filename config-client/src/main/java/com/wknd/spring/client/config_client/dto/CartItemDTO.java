package com.wknd.spring.client.config_client.dto;

import lombok.Data;

@Data
public class CartItemDTO {
    private String sku;
    private int quantity;
    private String title;
    private Double price;
    private String imagePath;
    private Boolean availability;
}
