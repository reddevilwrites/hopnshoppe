package com.hopnshoppe.cart.repository;

import com.hopnshoppe.cart.model.CartItem;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface CartItemRepository extends JpaRepository<CartItem, Long> {
    List<CartItem> findByUserEmail(String userEmail);
    Optional<CartItem> findByUserEmailAndSku(String userEmail, String sku);
    void deleteByUserEmailAndSku(String userEmail, String sku);
}
