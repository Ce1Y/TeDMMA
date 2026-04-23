import asyncio
import tree_sitter_java as tsjava
from pydantic import BaseModel, Field
from typing import List, Optional
from tree_sitter import Language, Parser, Query, QueryCursor
import re
from prettify_sexp import prettify_sexp
from text_processor import process_entity_features, process_java_captures, process_path_features, process_repository_features

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

def classify_java_file(matches, source_code):
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')

    # 收集類別上方的所有註解名稱
    annotations = set()
    for _, captures in matches:
        if 'class.type' in captures:
            for node in captures['class.type']:
                annotations.add(get_text(node))

    # 判定邏輯（優先權排序）
    if any(a in annotations for a in ["RestController", "Controller"]):
        return "CONTROLLER"
    if "Service" in annotations:
        return "SERVICE"
    if any(a in annotations for a in ["Entity", "Table", "Document"]):
        return "ENTITY"
    if any(a in annotations for a in ["Repository", "Component"]):
        return "REPOSITORY"
    
    return "UNKNOWN"


def extract_features(item: tuple):
    code_content = item[1]
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    # print(prettify_sexp(str(root_node)))
    
    classification = item[0]
    
    if classification == "UNKNOWN":
        query = Query(
            JAVA_LANGUAGE,
            """
            (class_declaration
                (modifiers
                    [
                        (marker_annotation name: (identifier) @class.type)
                        (annotation name: (identifier) @class.type)
                    ]
                )
            ) @class.root
            """
        )
        
        query_cursor = QueryCursor(query)
        matches = query_cursor.matches(tree.root_node)
        
        classification = classify_java_file(matches, code_bytes)
        
    if classification == "ENTITY":
        return extract_entity_features(code_content)
    elif classification == "CONTROLLER" or classification == "SERVICE":
        return extract_class_features(code_content, True)
    elif classification == "REPOSITORY":
        return extract_repository_features(code_content)
    else:
        # pass
        return extract_class_features(code_content)


def extract_class_features(code_content: str, is_controller=False):
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    # print(tree)
    # print(root_node)
    # print(prettify_sexp(str(root_node)))

    query = Query(
        JAVA_LANGUAGE,
        """
        ;; 1. 抓取類別資訊與註解 (用於判斷 class_name, component_type, annotations)
            (class_declaration
            (modifiers
                [
                    (marker_annotation name: (identifier) @class.annotation)
                    (annotation name: (identifier) @class.annotation)
                ] *
            )
            name: (identifier) @class.name
            ) @class.definition

            ;; 2. 抓取依賴關係 (用於 dependencies)
            ;; 通常位於 field_declaration 或 constructor_declaration
            (field_declaration
                type: [
                    (type_identifier) @dep.type
                    (generic_type) @dep.type
                ]
                declarator: (variable_declarator name: (identifier) @dep.name)
            ) @class.dependency

            ;; 3. 抓取方法特徵 (用於 methods: MethodSignature)
            (method_declaration
                type: [
                    (type_identifier)
                    (generic_type)
                    (void_type)
                ] @method.return_type
                name: (identifier) @method.name
                parameters: (formal_parameters
                    (formal_parameter
                    type: [
                        (type_identifier)
                        (generic_type)
                    ] @method.param_type
                    name: (identifier) @method.param_name
                    )*
                )
            ) @method.definition
        """
    )
    
    query_cursor = QueryCursor(query)
    matches = query_cursor.matches(tree.root_node)
    # print(matches)
    
    features_result =  process_java_captures(matches, code_bytes)
    if is_controller:
        path_features = extract_path_features(code_content)
        
        features_result.class_path = path_features.get('class_path', "./")
        methods_mapping = path_features.get('methods_path', {})
        
        for method in features_result.methods:
            if method.name in methods_mapping:
                method.method_path = methods_mapping[method.name]

    return features_result.model_dump()


def extract_path_features(code_content: str):
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    query = Query(
        JAVA_LANGUAGE,
        """
        (class_declaration
            (modifiers
                (annotation
                    name: (identifier) @class.anno_name
                    arguments: (annotation_argument_list
                        [
                            ;; 直接寫路徑: @RequestMapping("/api")
                            (string_literal (string_fragment) @path.class)
                            ;; 具名參數: @RequestMapping(value = "/api")
                            (element_value_pair 
                                key: (identifier) @key (#match? @key "value|path")
                                value: (string_literal (string_fragment) @path.class))
                        ]
                    )
                )
            )
        )

        (method_declaration
            (modifiers
                (annotation
                    name: (identifier) @method.anno_name (#match? @method.anno_name ".*Mapping")
                    arguments: (annotation_argument_list
                        [
                            ;; 直接寫路徑: @GetMapping("/users")
                            (string_literal (string_fragment) @path.method)
                            ;; 具名參數: @PostMapping(path = "/create")
                            (element_value_pair 
                                key: (identifier) @key (#match? @key "value|path")
                                value: (string_literal (string_fragment) @path.method))
                        ]
                    )
                )
            )
            name: (identifier) @method.name 
        )
        """
    )
    
    query_cursor = QueryCursor(query)
    matches = query_cursor.matches(tree.root_node)
    # print(matches)
    
    return process_path_features(matches, code_bytes)


def extract_entity_features(code_content: str):
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    # print(prettify_sexp(str(root_node)))

    # 使用 Tree-sitter Query (S-expression) 尋找註解與類別名
    query = Query(
        JAVA_LANGUAGE,
        """
        (class_declaration
            name: (identifier) @entity.name
            body: (class_body
                [
                    ;; 抓取帶有註解的欄位
                    (field_declaration
                        (modifiers
                            [
                                (marker_annotation name: (identifier) @field.annotation)
                                (annotation name: (identifier) @field.annotation)
                            ]
                        )*
                        type: [
                            (type_identifier) @field.type
                            (generic_type) @field.type
                        ]
                        declarator: (variable_declarator
                        name: (identifier) @field.name)
                    ) @entity.field

                    ;; 抓取內部的 Enum 定義
                    (enum_declaration
                        name: (identifier) @enum.name
                        body: (enum_body
                            (enum_constant name: (identifier) @enum.member)*
                        )
                    ) @entity.enum
                ]
            )
        )
        """
    )
    
    query_cursor = QueryCursor(query)
    matches = query_cursor.matches(tree.root_node)
    # print(matches)
    
    return process_entity_features(matches, code_bytes)


def extract_repository_features(code_content: str):
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    # print(prettify_sexp(str(root_node)))
    
    query = Query(
        JAVA_LANGUAGE,
        """
        ;; === Repository 核心定義 ===
        (interface_declaration
            (modifiers
                (marker_annotation 
                name: (identifier) @repo.anno (#eq? @repo.anno "Repository")
                )?
            )
            name: (identifier) @repo.name
        ;; 擷取繼承關係與泛型參數
        (extends_interfaces
            (type_list
                (generic_type
                    (type_identifier) @repo.base_interface (#match? @repo.base_interface "Repository|JpaRepository|CrudRepository|PagingAndSortingRepository")
                        (type_arguments
                            [
                                (type_identifier) @repo.managed_entity
                                (generic_type) @repo.managed_entity
                            ]
                            (type_identifier) @repo.id_type
                        )
                    )
                )
            )
        ) @repo.definition

        ;; === 自定義查詢方法 (Query Methods) ===
        (method_declaration
            type: [
                (type_identifier) 
                (generic_type)
            ] @method.return_type
            name: (identifier) @method.name
            parameters: (formal_parameters) @method.params
        ) @repo.method
        """
    )
    
    query_cursor = QueryCursor(query)
    matches = query_cursor.matches(tree.root_node)
    # print(matches)
    
    features_result =  process_repository_features(matches, code_bytes)
    # print(features_result)
    
    return features_result.model_dump()


