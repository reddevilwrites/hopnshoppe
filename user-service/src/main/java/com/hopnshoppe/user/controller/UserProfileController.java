package com.hopnshoppe.user.controller;

import com.hopnshoppe.common.dto.UserDTO;
import com.hopnshoppe.user.service.UserProfileService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Public-facing user profile lookup by database ID.
 *
 * <p>Accessed externally via the API gateway route:
 * <pre>
 *   GET /api/user/{id}
 *   → gateway RewritePath → GET /users/{id} (this controller)
 * </pre>
 *
 * <p>No authentication required — profile data (name, email) is considered
 * non-sensitive for display purposes. Exclude phone if sensitivity is a concern
 * by projecting a slimmer DTO here instead of the full UserDTO.
 */
@RestController
@RequestMapping("/users")
public class UserProfileController {

    private final UserProfileService service;

    public UserProfileController(UserProfileService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    public UserDTO getById(@PathVariable Long id) {
        return service.getById(id);
    }
}
