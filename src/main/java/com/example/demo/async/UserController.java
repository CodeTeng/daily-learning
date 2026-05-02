package com.example.demo.controller;

import com.example.demo.model.User;
import com.example.demo.service.UserService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/users")
public class UserController {

    private static final Logger log = LoggerFactory.getLogger(UserController.class);

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    public record RegisterRequest(String name, String email, String phone) {
    }

    @PostMapping
    public User register(@RequestBody RegisterRequest req) {
        long t0 = System.currentTimeMillis();
        User user = userService.register(req.name(), req.email(), req.phone());
        long elapsed = System.currentTimeMillis() - t0;
        log.info("[controller] 接口在 {} ms 内返回（邮件/短信仍在后台跑）", elapsed);
        return user;
    }
}
