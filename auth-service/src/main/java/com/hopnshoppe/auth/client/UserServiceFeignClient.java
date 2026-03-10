package com.hopnshoppe.auth.client;

import com.hopnshoppe.common.dto.UserDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

/**
 * Feign client for calling user-service's internal API.
 *
 * <p>{@code name = "user-service"} resolves to the actual host:port at runtime
 * via the Eureka registry — no hardcoded URLs. Spring Cloud LoadBalancer
 * picks an instance using a round-robin strategy automatically.
 *
 * <h2>Endpoints consumed</h2>
 * <ul>
 *   <li>{@code POST /internal/users} — create profile during signup</li>
 *   <li>{@code GET /internal/users/by-email/{email}} — fetch display name on login</li>
 * </ul>
 *
 * <p>The calling methods in {@link com.hopnshoppe.auth.service.UserDisplayAdapter}
 * wrap these calls in a Resilience4j circuit breaker to handle user-service downtime.
 */
@FeignClient(name = "user-service")
public interface UserServiceFeignClient {

    @PostMapping("/internal/users")
    UserDTO createProfile(@RequestBody UserDTO dto);

    @GetMapping("/internal/users/by-email/{email}")
    UserDTO getUserByEmail(@PathVariable("email") String email);
}
