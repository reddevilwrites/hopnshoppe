package com.hopnshoppe.common.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Shared user representation passed between services.
 *
 * <p>Used in two inter-service flows:
 * <ul>
 *   <li>auth-service → user-service: {@code POST /internal/users} (profile creation on signup)</li>
 *   <li>user-service → callers: {@code GET /internal/users/{email}} (profile lookup)</li>
 * </ul>
 *
 * <p>Does NOT contain credentials (password hash lives only in auth-service's database).
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UserDTO {

    @Email(message = "Must be a valid email address")
    @NotBlank(message = "Email is required")
    private String email;

    @NotBlank(message = "First name is required")
    @Size(min = 2, max = 50)
    private String firstName;

    @NotBlank(message = "Last name is required")
    @Size(min = 2, max = 50)
    private String lastName;

    @Pattern(regexp = "^\\+?[0-9]*$", message = "Invalid phone number")
    private String phone;
}
