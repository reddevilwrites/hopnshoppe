package com.wknd.spring.client.config_client.controller;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import jakarta.annotation.PostConstruct;
//This was implemented for the authentication through api key
@RestController
@RequestMapping("/api")
public class ProxyController {
    
    @Value("${security.api-key}")
    private String apiKey;

    @Value("${api.target-url}")
    private String targetUrl;

    private static final Logger logger = LoggerFactory.getLogger(ProxyController.class);

    private final RestTemplate restTemplate = new RestTemplate();

    @PostConstruct
    public void init() {
        System.out.println("Injected API Key: " + apiKey);
    }

    @GetMapping("/products")
    public ResponseEntity<String> proxyProducts() {
        HttpHeaders headers = new HttpHeaders();

        headers.set("X-API-KEY", apiKey);
        headers.setAccept(MediaType.parseMediaTypes("application/json"));

        HttpEntity<String> request = new HttpEntity<>(headers);

        try {
            ResponseEntity<String> response = restTemplate.exchange(
                targetUrl,
                HttpMethod.GET,
                request,
                String.class
            );
            logger.debug("response.getStatusCode() :: {}",response.getStatusCode());
            return ResponseEntity.status(response.getStatusCode()).body(response.getBody());
        } catch (Exception e) {
             return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                                 .body("{\"error\": \"Failed to fetch products from upstream service\"}");
        }
    }
}
