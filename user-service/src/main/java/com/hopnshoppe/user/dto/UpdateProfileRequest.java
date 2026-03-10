package com.hopnshoppe.user.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

/**
 * Request body for PUT /account/me.
 * Email is intentionally included so a user can change their display email;
 * the canonical auth email (in auth-service) is not affected by this change.
 */
@Data
public class UpdateProfileRequest {

    @Email
    @NotBlank
    private String email;

    @NotBlank
    @Size(min = 2, max = 50)
    private String firstName;

    @NotBlank
    @Size(min = 2, max = 50)
    private String lastName;

    @Pattern(regexp = "^\\+?[0-9]*$", message = "Invalid phone number")
    private String phone;
}
