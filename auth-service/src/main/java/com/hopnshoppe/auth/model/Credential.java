package com.hopnshoppe.auth.model;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Stores authentication credentials exclusively in auth-service's database (auth_db).
 *
 * <p>Only email and password hash live here. Profile data (firstName, lastName, phone)
 * is owned by user-service. The email column is the cross-service join key but there
 * is intentionally no foreign key — database-per-service forbids cross-DB constraints.
 */
@Entity
@Table(name = "credentials",
       uniqueConstraints = @UniqueConstraint(columnNames = "email"))
@Data
@NoArgsConstructor
@AllArgsConstructor
public class Credential {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private String email;

    @Column(name = "password_hash", nullable = false)
    private String passwordHash;
}
