package com.hopnshoppe.cart.service;

import com.hopnshoppe.cart.client.CatalogClient;
import com.hopnshoppe.cart.dto.CartItemDTO;
import com.hopnshoppe.cart.dto.ProductDTO;
import com.hopnshoppe.cart.model.CartItem;
import com.hopnshoppe.cart.repository.CartItemRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
public class CartService {

    private final CartItemRepository cartItemRepository;
    private final CatalogClient catalogClient;

    public CartService(CartItemRepository cartItemRepository, CatalogClient catalogClient) {
        this.cartItemRepository = cartItemRepository;
        this.catalogClient = catalogClient;
    }

    @Transactional
    public CartItemDTO addItem(String userEmail, String sku, int quantity) {
        int qtyToAdd = Math.max(1, quantity);
        CartItem item = cartItemRepository.findByUserEmailAndSku(userEmail, sku)
                .orElseGet(() -> {
                    CartItem c = new CartItem();
                    c.setUserEmail(userEmail);
                    c.setSku(sku);
                    c.setQuantity(0);
                    return c;
                });
        item.setQuantity(item.getQuantity() + qtyToAdd);
        return toDto(cartItemRepository.save(item));
    }

    public List<CartItemDTO> getCart(String userEmail) {
        return cartItemRepository.findByUserEmail(userEmail).stream()
                .map(this::toDto)
                .collect(Collectors.toList());
    }

    @Transactional
    public CartItemDTO incrementItem(String userEmail, String sku) {
        CartItem item = cartItemRepository.findByUserEmailAndSku(userEmail, sku)
                .orElseThrow(() -> new IllegalArgumentException("Item not found in cart"));
        item.setQuantity(item.getQuantity() + 1);
        return toDto(cartItemRepository.save(item));
    }

    @Transactional
    public CartItemDTO decrementItem(String userEmail, String sku) {
        CartItem item = cartItemRepository.findByUserEmailAndSku(userEmail, sku)
                .orElseThrow(() -> new IllegalArgumentException("Item not found in cart"));
        if (item.getQuantity() <= 1) {
            cartItemRepository.delete(item);
            return null;
        }
        item.setQuantity(item.getQuantity() - 1);
        return toDto(cartItemRepository.save(item));
    }

    @Transactional
    public void removeItem(String userEmail, String sku) {
        cartItemRepository.findByUserEmailAndSku(userEmail, sku)
                .ifPresent(cartItemRepository::delete);
    }

    private CartItemDTO toDto(CartItem item) {
        CartItemDTO dto = new CartItemDTO();
        dto.setSku(item.getSku());
        dto.setQuantity(item.getQuantity());
        ProductDTO product = catalogClient.getProductBySku(item.getSku());
        if (product != null) {
            dto.setTitle(product.title);
            dto.setPrice(product.price);
            dto.setAvailability(product.availability);
            dto.setImagePath(product.imagePath);
        }
        return dto;
    }
}
