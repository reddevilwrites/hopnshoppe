package com.hopnshoppe.user;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

/**
 * HopNShoppe User Service.
 *
 * <p>Owns all non-sensitive user profile data (name, email, phone).
 * Credentials (password hash) live exclusively in auth-service.
 *
 * <p>Exposes three groups of endpoints:
 * <ul>
 *   <li>{@code /users/{id}} — public profile lookup (via gateway: {@code /api/user/{id}})</li>
 *   <li>{@code /account/me} — authenticated profile management (via gateway: {@code /api/user/account/me})</li>
 *   <li>{@code /internal/**} — service-to-service API, not routed through the gateway</li>
 * </ul>
 */
@SpringBootApplication
@EnableDiscoveryClient
public class UserServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(UserServiceApplication.class, args);
    }
}
