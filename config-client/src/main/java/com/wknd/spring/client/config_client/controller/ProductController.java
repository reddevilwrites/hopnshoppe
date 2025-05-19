package com.wknd.spring.client.config_client.controller;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.wknd.spring.client.config_client.model.ProductDTO;
import com.wknd.spring.client.config_client.service.ProductService;

@CrossOrigin(origins = "http://localhost:5173")
@RestController
@RequestMapping("/products")
public class ProductController {
    private final ProductService service;
    private static final Logger logger = LoggerFactory.getLogger(ProductController.class);

    public ProductController(ProductService service) {
        this.service = service;
    }

    @GetMapping
    public List<ProductDTO> getProducts(@RequestParam(required = false) String category, @RequestParam(required = false) Boolean availability) {
        logger.info("Inside /products endpoint"); 
        return service.fetchFilteredProducts(category, availability);
    }

    @GetMapping("/{sku}")
    public ProductDTO getProductBySku(@PathVariable String sku){
        return service.fetchProductBySku(sku);
    }

}
