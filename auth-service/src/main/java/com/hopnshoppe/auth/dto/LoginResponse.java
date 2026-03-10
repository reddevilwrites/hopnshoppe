package com.hopnshoppe.auth.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

/**
 * Response for POST /auth/login.
 *
 * <p>Extends the monolith's {@code { "token": "..." }} with a {@code displayName}
 * field populated by the Feign call to user-service. The frontend can show
 * "Welcome, John Doe" immediately after login without a second round-trip.
 *
 * <p>If user-service is unavailable, {@code displayName} gracefully falls back
 * to the user's email address (see {@code UserDisplayAdapter.displayNameFallback}).
 */
@Data
@AllArgsConstructor
public class LoginResponse {

    private String token;

    /**
     * The user's full name fetched from user-service (firstName + " " + lastName).
     * Falls back to the user's email if user-service is unreachable.
     */
    private String displayName;
}
