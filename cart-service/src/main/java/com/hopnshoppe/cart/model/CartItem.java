package com.hopnshoppe.cart.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Cart item entity.
 *
 * <p>The monolith stored a {@code @ManyToOne User} FK. In the microservice model
 * there is no cross-database FK: we store the user's email (the JWT subject) as
 * a plain {@code VARCHAR} column. This breaks the coupling to user-service's database.
 */
@Entity
@Table(name = "cart_items",
        uniqueConstraints = @UniqueConstraint(columnNames = {"user_email", "sku"}))
@Data
@NoArgsConstructor
public class CartItem {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_email", nullable = false)
    private String userEmail;

    @Column(nullable = false)
    private String sku;

    @Column(nullable = false)
    private int quantity;
}
