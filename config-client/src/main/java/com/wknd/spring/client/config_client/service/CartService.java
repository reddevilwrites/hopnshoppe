package com.wknd.spring.client.config_client.service;

import java.util.List;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.wknd.spring.client.config_client.dto.CartItemDTO;
import com.wknd.spring.client.config_client.model.CartItem;
import com.wknd.spring.client.config_client.model.User;
import com.wknd.spring.client.config_client.repository.CartItemRepository;
import com.wknd.spring.client.config_client.repository.UserRepository;

@Service
public class CartService {
    private final CartItemRepository cartItemRepository;
    private final UserRepository userRepository;
    private final ProductService productService;

    public CartService(CartItemRepository cartItemRepository, UserRepository userRepository, ProductService productService) {
        this.cartItemRepository = cartItemRepository;
        this.userRepository = userRepository;
        this.productService = productService;
    }

    @Transactional
    public CartItemDTO addItem(String userEmail, String sku, int quantity) {
        User user = userRepository.findByEmail(userEmail);
        if (user == null) {
            throw new IllegalArgumentException("User not found");
        }

        int qtyToAdd = Math.max(1, quantity);
        CartItem cartItem = cartItemRepository.findByUserAndSku(user, sku)
            .orElseGet(() -> {
                CartItem c = new CartItem();
                c.setUser(user);
                c.setSku(sku);
                c.setQuantity(0);
                return c;
            });

        cartItem.setQuantity(cartItem.getQuantity() + qtyToAdd);
        CartItem saved = cartItemRepository.save(cartItem);
        return toDto(saved);
    }

    public List<CartItemDTO> getCart(String userEmail) {
        User user = userRepository.findByEmail(userEmail);
        if (user == null) {
            throw new IllegalArgumentException("User not found");
        }

        return cartItemRepository.findByUser(user).stream()
            .map(this::toDto)
            .collect(Collectors.toList());
    }

    @Transactional
    public CartItemDTO updateQuantity(String userEmail, String sku, int quantity) {
        User user = userRepository.findByEmail(userEmail);
        if (user == null) {
            throw new IllegalArgumentException("User not found");
        }

        return cartItemRepository.findByUserAndSku(user, sku)
            .map(item -> {
                if (quantity <= 0) {
                    cartItemRepository.delete(item);
                    return null;
                }
                item.setQuantity(quantity);
                return toDto(cartItemRepository.save(item));
            })
            .orElseThrow(() -> new IllegalArgumentException("Item not found in cart"));
    }

    @Transactional
    public void removeItem(String userEmail, String sku) {
        User user = userRepository.findByEmail(userEmail);
        if (user == null) {
            throw new IllegalArgumentException("User not found");
        }
        cartItemRepository.findByUserAndSku(user, sku).ifPresent(cartItemRepository::delete);
    }

    private CartItemDTO toDto(CartItem item) {
        CartItemDTO dto = new CartItemDTO();
        dto.setSku(item.getSku());
        dto.setQuantity(item.getQuantity());
        var product = productService.fetchProductBySku(item.getSku());
        if (product != null) {
            dto.setTitle(product.title);
            dto.setPrice(product.price);
            dto.setAvailability(product.availability);
            dto.setImagePath(product.imagePath);
        }
        return dto;
    }
}
