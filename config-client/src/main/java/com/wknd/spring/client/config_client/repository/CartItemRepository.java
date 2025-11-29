package com.wknd.spring.client.config_client.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import com.wknd.spring.client.config_client.model.CartItem;
import com.wknd.spring.client.config_client.model.User;

public interface CartItemRepository extends JpaRepository<CartItem, Long>{
    List<CartItem> findByUser(User user);
    Optional<CartItem> findByUserAndSku(User user, String sku);
}
