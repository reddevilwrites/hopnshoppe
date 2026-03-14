package com.hopnshoppe.cart.service;

import com.hopnshoppe.cart.client.CatalogClient;
import com.hopnshoppe.cart.dto.CartItemDTO;
import com.hopnshoppe.cart.model.CartItem;
import com.hopnshoppe.cart.repository.CartItemRepository;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
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
        return enriched(cartItemRepository.save(item));
    }

    public List<CartItemDTO> getCart(String userEmail) {
        List<CartItem> items = cartItemRepository.findByUserEmail(userEmail);
        if (items.isEmpty()) return List.of();

        List<String> skus = items.stream().map(CartItem::getSku).collect(Collectors.toList());
        Map<String, UnifiedProductDTO> productMap = catalogClient.getUnifiedProductsByIds(skus).stream()
                .collect(Collectors.toMap(UnifiedProductDTO::getId, p -> p, (a, b) -> a));

        return items.stream().map(item -> {
            CartItemDTO dto = new CartItemDTO();
            dto.setSku(item.getSku());
            dto.setQuantity(item.getQuantity());
            UnifiedProductDTO product = productMap.get(item.getSku());
            if (product != null) {
                dto.setName(product.getName());
                dto.setPrice(product.getPrice());
                dto.setImageUrl(product.getImageUrl());
            }
            return dto;
        }).collect(Collectors.toList());
    }

    @Transactional
    public CartItemDTO incrementItem(String userEmail, String sku) {
        CartItem item = cartItemRepository.findByUserEmailAndSku(userEmail, sku)
                .orElseThrow(() -> new IllegalArgumentException("Item not found in cart"));
        item.setQuantity(item.getQuantity() + 1);
        return enriched(cartItemRepository.save(item));
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
        return enriched(cartItemRepository.save(item));
    }

    @Transactional
    public void removeItem(String userEmail, String sku) {
        cartItemRepository.findByUserEmailAndSku(userEmail, sku)
                .ifPresent(cartItemRepository::delete);
    }

    private CartItemDTO enriched(CartItem item) {
        CartItemDTO dto = new CartItemDTO();
        dto.setSku(item.getSku());
        dto.setQuantity(item.getQuantity());
        UnifiedProductDTO product = catalogClient.getUnifiedProductById(item.getSku());
        if (product != null) {
            dto.setName(product.getName());
            dto.setPrice(product.getPrice());
            dto.setImageUrl(product.getImageUrl());
        }
        return dto;
    }

}
