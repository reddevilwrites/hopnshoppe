package com.hopnshoppe.catalog.model;

public class Product {
    public String title;
    public String sku;
    public Description description;
    public double price;
    public boolean availability;
    public String category;
    public String imagePath;

    public static class Description {
        public String plaintext;
    }
}
