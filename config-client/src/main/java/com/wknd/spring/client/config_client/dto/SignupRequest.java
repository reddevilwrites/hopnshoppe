package com.wknd.spring.client.config_client.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class SignupRequest {
    
    @Email
    @NotNull
    private String email;

    @NotNull
    @Size(min = 2, max=50)
    private String firstName;

    @NotNull
    @Size
    private String lastName;

    @Pattern(regexp = "^\\+?[0-9]*$", message = "Invalid Phone number")
    private String phone;

    @NotNull
    @Size(min = 8, max = 100)
    private String password;
}
