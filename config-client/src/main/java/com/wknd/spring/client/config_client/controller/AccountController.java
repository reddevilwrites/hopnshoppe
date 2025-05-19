package com.wknd.spring.client.config_client.controller;

import org.springframework.boot.actuate.web.exchanges.HttpExchange.Principal;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.wknd.spring.client.config_client.dto.UpdateProfileDTO;
import com.wknd.spring.client.config_client.dto.UserProfileDTO;
import com.wknd.spring.client.config_client.model.User;
import com.wknd.spring.client.config_client.service.UserService;

import jakarta.validation.Valid;

@RestController
@RequestMapping("/account")
public class AccountController {
    private final UserService userService;

    public AccountController(UserService userService){
        this.userService = userService;
    }

    @GetMapping("/me")
    public UserProfileDTO getUserProfile(Authentication authentication){
        return userService.getUserProfile(authentication.getName());
    }

    @PutMapping("/me")
    public UserProfileDTO updateUserProfile(Authentication authentication, @RequestBody @Valid UpdateProfileDTO updateProfileDTO){
        return userService.updateUserProfile(authentication.getName(), updateProfileDTO);
    }
    
}
