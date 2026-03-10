package com.hopnshoppe.cart.controller;

import com.hopnshoppe.cart.dto.CartItemDTO;
import com.hopnshoppe.cart.service.CartService;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/cart")
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

    @PostMapping("/{sku}/increment")
    public ResponseEntity<?> increment(@PathVariable String sku, Authentication authentication) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        try {
            return ResponseEntity.ok(cartService.incrementItem(authentication.getName(), sku));
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.badRequest().body(ex.getMessage());
        }
    }

    @PostMapping("/{sku}/decrement")
    public ResponseEntity<?> decrement(@PathVariable String sku, Authentication authentication) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        try {
            CartItemDTO updated = cartService.decrementItem(authentication.getName(), sku);
            if (updated == null) {
                // quantity reached 0 — item removed
                return ResponseEntity.noContent().build();
            }
            return ResponseEntity.ok(updated);
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.badRequest().body(ex.getMessage());
        }
    }

    @DeleteMapping("/{sku}")
    public ResponseEntity<Void> remove(@PathVariable String sku, Authentication authentication) {
        if (authentication == null) {
            return ResponseEntity.status(401).build();
        }
        cartService.removeItem(authentication.getName(), sku);
        return ResponseEntity.noContent().build();
    }
}
