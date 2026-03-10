package com.hopnshoppe.user.controller;

import com.hopnshoppe.common.dto.UserDTO;
import com.hopnshoppe.user.dto.UpdateProfileRequest;
import com.hopnshoppe.user.service.UserProfileService;
import jakarta.validation.Valid;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

/**
 * Authenticated account management — migrated from the monolith's AccountController.
 *
 * <p>Requires a valid JWT. The authenticated user's email is read from the
 * Spring Security context (populated by JwtFilter), exactly as in the monolith.
 *
 * <p>Gateway path mapping (via RewritePath):
 * <pre>
 *   GET /api/user/account/me  →  GET /account/me
 *   PUT /api/user/account/me  →  PUT /account/me
 * </pre>
 */
@RestController
@RequestMapping("/account")
public class AccountController {

    private final UserProfileService service;

    public AccountController(UserProfileService service) {
        this.service = service;
    }

    /** Returns the authenticated user's own profile. */
    @GetMapping("/me")
    public UserDTO getProfile(Authentication authentication) {
        return service.getByEmail(authentication.getName());
    }

    /** Updates mutable profile fields. Email change is allowed; password is managed by auth-service. */
    @PutMapping("/me")
    public UserDTO updateProfile(Authentication authentication,
                                 @RequestBody @Valid UpdateProfileRequest request) {
        return service.updateProfile(authentication.getName(), request);
    }
}
