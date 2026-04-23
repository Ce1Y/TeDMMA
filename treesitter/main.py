import tree_sitter_java as tsjava
from tree_sitter import Language, Parser
import feature_capture as fc
import asyncio
import text_processor
import json

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

### ======== Target File ======== ###
TARGET_ZIP_FILE = "brewery-monolith-master"
### ======== Target File ======== ###

# ===== Testing code snippets =====
code_controller = """
package com.example.ecommerce.controller;

import com.example.ecommerce.model.entity.Product;
import com.example.ecommerce.service.ProductService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Tag(name = "Product API", description = "商品管理相關操作")
@RestController
@RequestMapping("api/products")
public class ProductController {

    private final ProductService productService;

    public ProductController(ProductService productService) {
        this.productService = productService;
    }

    @Operation(summary = "取得所有商品")
    @GetMapping("/all")
    public List<Product> getAllProducts() {
        return productService.getAllProducts();
    }

    @Operation(summary = "依ID取得商品")
    @GetMapping("/{id}")
    public ResponseEntity<Product> getProductById(@PathVariable Long id) {
        try {
            Product product = productService.getProductById(id);
            return ResponseEntity.ok(product);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.notFound().build();
        }
    }

    @Operation(summary = "新增商品")
    @PostMapping
    public Product createProduct(@RequestBody Product product) {
        return productService.createProduct(product);
    }

    @Operation(summary = "更新商品")
    @PutMapping("/{id}")
    public Product updateProduct(@PathVariable Long id, @RequestBody Product product) {
        return productService.updateProduct(id, product);
    }

    @Operation(summary = "刪除商品")
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteProduct(@PathVariable Long id) {
        productService.deleteProductById(id);
        return ResponseEntity.noContent().build();
    }
}

"""
code_service = """
package com.example.ecommerce.service;

import com.example.ecommerce.model.entity.Product;
import com.example.ecommerce.repository.ProductRepository;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class ProductService {
    private final ProductRepository productRepository;
    public ProductService(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    public List<Product> getAllProducts() {
        return productRepository.findAll();
    }

    public Product getProductById(Long id) {
        return productRepository.findById(id).orElseThrow(() -> new IllegalArgumentException("Product not found"));
    }

    public Product createProduct(Product product) {
        return productRepository.save(product);
    }

    public Product updateProduct(Long id, Product updatedProduct) {
        return productRepository.findById(id).map(product -> {
            product.setName(updatedProduct.getName());
            product.setDescription(updatedProduct.getDescription());
            product.setPrice(updatedProduct.getPrice());
            product.setStock(updatedProduct.getStock());
            return productRepository.save(product);
        }).orElseThrow(() -> new RuntimeException("Product not found with id: " + id));
    }

    public void deleteProductById(Long id) {
        productRepository.deleteById(id);
    }

    public void deleteAllProducts() {
        productRepository.deleteAll();
    }
}

"""
code_entity_member = """
package com.example.ecommerce.model.entity;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "members")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Member {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private String username;

    @Column(nullable = false)
    private String password;

    private String email;
    private String phone;

    @Enumerated(EnumType.STRING)
    private Role role;

    public enum Role {
        MEMBER, ADMIN
    }
}
"""
code_repository = """
package com.example.ecommerce.repository;

import com.example.ecommerce.model.entity.Member;
import com.example.ecommerce.model.entity.Order;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface OrderRepository extends JpaRepository<Order, Long> {
    List<Order> findByMemberId(Long Id);
}
"""
code_entity_order = """
package com.example.ecommerce.model.entity;

import com.example.ecommerce.model.enums.OrderStatus;
import com.fasterxml.jackson.annotation.JsonManagedReference;
import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "orders")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Order {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne
    @JoinColumn(name = "member_id", nullable = false)
    private Member member;

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true)
    @JsonManagedReference   
    private List<OrderItem> items;

    @Enumerated(EnumType.STRING)
    private OrderStatus status;

    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
"""
# ===== Testing code snippets =====

# print(fc.extract_class_features(code_controller))
# print(fc.extract_path_features(code_controller))
# print(fc.extract_class_features(code_service))
# print(fc.extract_path_features(code_service))
# print(fc.extract_entity_features(code_entity_member))
# print(fc.extract_entity_features(code_entity_order))
# fc.extract_repository_features(code_repository)

async def main():
    result = text_processor.load_java_project("migrate_project/" + TARGET_ZIP_FILE + ".zip")
    
    prompt_features = ""
    prompt_test_cases = "### Test Source Code ###\n" # 存放測試檔案內容的另一個 Prompt
    
    for item in result:
        class_type = item[0]    
        code_content = item[1]  
        
        if class_type == "TEST":
            prompt_test_cases += f"\n--- Test File ---\n{code_content}\n"
            continue 
        
        features = fc.extract_features(item)
        # print(features)
        # print("\n")
        
        if features != None:
            if "class_name" in features:
                prompt_features += "Class:\n" + str(features) + "\n\n"
            elif "entity_name" in features:
                prompt_features += "Entity:\n" + str(features) + "\n\n"
            elif "repo_name" in features:
                prompt_features += "Repository:\n" + str(features) + "\n\n"
                
    with open("api-docs.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    prompt_test_cases += "\n### API Documentation (JSON) ###\n"
    prompt_test_cases += str(data)
            
    print(prompt_features)
    # print(prompt_test_cases)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


