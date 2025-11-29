package com.wknd.spring.client.config_client.controller;

import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.wknd.spring.client.config_client.dto.CartItemDTO;
import com.wknd.spring.client.config_client.service.CartService;

@RestController
@RequestMapping("/cart")
@CrossOrigin(origins = "http://localhost:5173")
public class CartController {

    private final CartService cartService;

    public CartController(CartService cartService) {
        this.cartService = cartService;
    }

    @GetMapping
    public ResponseEntity<List<CartItemDTO>> getCart(Authentication authentication) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(cartService.getCart(authentication.getName()));
    }

    @PostMapping("/{sku}")
    public ResponseEntity<CartItemDTO> addToCart(
            @PathVariable String sku,
            @RequestParam(name = "quantity", defaultValue = "1") int quantity,
            Authentication authentication) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(cartService.addItem(authentication.getName(), sku, quantity));
    }

    @PostMapping("/{sku}/decrement")
    public ResponseEntity<?> decrement(
        @PathVariable String sku,
        Authentication authentication
    ) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        try {
            CartItemDTO updated = cartService.updateQuantity(authentication.getName(), sku, cartService.getCart(authentication.getName()).stream()
                .filter(i -> i.getSku().equals(sku))
                .map(i -> i.getQuantity() - 1)
                .findFirst()
                .orElse(0));
            return ResponseEntity.ok(updated);
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.badRequest().body(ex.getMessage());
        }
    }

    @PostMapping("/{sku}/increment")
    public ResponseEntity<?> increment(
        @PathVariable String sku,
        Authentication authentication
    ) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        try {
            CartItemDTO updated = cartService.updateQuantity(authentication.getName(), sku, cartService.getCart(authentication.getName()).stream()
                .filter(i -> i.getSku().equals(sku))
                .map(i -> i.getQuantity() + 1)
                .findFirst()
                .orElse(1));
            return ResponseEntity.ok(updated);
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.badRequest().body(ex.getMessage());
        }
    }

    @DeleteMapping("/{sku}")
    public ResponseEntity<Void> remove(
        @PathVariable String sku,
        Authentication authentication
    ) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        cartService.removeItem(authentication.getName(), sku);
        return ResponseEntity.noContent().build();
    }
}
