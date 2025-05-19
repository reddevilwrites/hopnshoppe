package com.wknd.spring.client.config_client.model;

import java.util.List;

public class ProductResponseWrapper {
    public Data data;

    public static class Data{
        public ProductList productList;
    }

    public static class ProductList{
        public List<Product> items;
    }
}
