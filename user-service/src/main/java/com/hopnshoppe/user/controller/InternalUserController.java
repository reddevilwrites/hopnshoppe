package com.hopnshoppe.user.controller;

import com.hopnshoppe.common.dto.UserDTO;
import com.hopnshoppe.user.service.UserProfileService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

/**
 * Service-to-service API — NOT exposed through the API gateway.
 *
 * <p>The gateway has no route for {@code /internal/**}, so these endpoints are
 * only reachable from within the Docker/k8s network by other services.
 *
 * <h2>Consumers</h2>
 * <ul>
 *   <li>{@code POST /internal/users} — called by auth-service during signup to create
 *       the matching profile record after the credential is persisted.</li>
 *   <li>{@code GET /internal/users/by-email/{email}} — called by auth-service's
 *       {@code UserServiceFeignClient} after login to fetch the display name.</li>
 * </ul>
 *
 * <h2>Production hardening (TODO)</h2>
 * In production, protect these endpoints with one of:
 * <ul>
 *   <li>mTLS between services</li>
 *   <li>A shared internal API key header validated by a dedicated filter</li>
 *   <li>Network-level policy (only the Docker bridge network / k8s namespace can reach port 8084)</li>
 * </ul>
 */
@RestController
@RequestMapping("/internal/users")
public class InternalUserController {

    private final UserProfileService service;

    public InternalUserController(UserProfileService service) {
        this.service = service;
    }

    /**
     * Creates a profile record during the signup flow.
     * Returns 201 Created with the persisted profile.
     * Returns 409 Conflict (via ConflictException → GlobalExceptionHandler)
     * if a profile for that email already exists, signalling auth-service to roll back.
     */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public UserDTO createProfile(@RequestBody @Valid UserDTO dto) {
        return service.createProfile(dto);
    }

    /**
     * Fetches a profile by email. Called by auth-service's Feign client on login
     * to retrieve the display name (firstName + lastName) for the login response.
     */
    @GetMapping("/by-email/{email}")
    public UserDTO getByEmail(@PathVariable String email) {
        return service.getByEmail(email);
    }

    /**
     * Deletes a profile by email. Used by the Playwright E2E test teardown to
     * clean up test accounts after each test run.
     * Not exposed through the API gateway — reachable only within the Docker/k8s network.
     */
    @DeleteMapping("/{email}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteUser(@PathVariable String email) {
        service.deleteByEmail(email);
    }
}
