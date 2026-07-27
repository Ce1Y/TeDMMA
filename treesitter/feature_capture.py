import asyncio
import tree_sitter_java as tsjava
from pydantic import BaseModel, Field
from typing import List, Optional
from tree_sitter import Language, Parser, Query, QueryCursor
import re
from prettify_sexp import prettify_sexp
from text_processor import process_entity_features, process_java_captures, process_path_features, process_repository_features, process_dto_features

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

def classify_java_file(matches, source_code):
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')

    annotations = set()
    for _, captures in matches:
        if 'class.type' in captures:
            for node in captures['class.type']:
                annotations.add(get_text(node))

    # 1. Web 層級判斷
    if any(a in annotations for a in ["RestController", "Controller"]):
        return "CONTROLLER"
    
    # 2. 業務邏輯層級判斷
    if "Service" in annotations:
        return "SERVICE"
    
    # 3. 持久層判斷 (優先於 DTO，因為 Entity 常掛 Lombok 註解)
    if any(a in annotations for a in ["Entity", "Table", "Document", "Id", "MappedSuperclass"]):
        return "ENTITY"
    
    # 4. 倉儲層判斷
    if any(a in annotations for a in ["Repository"]):
        return "REPOSITORY"

    # 5. DTO 判斷 (Data Transfer Object / Value Object)
    dto_indicators = {
        "Data", "Value", "Builder", 
        "NoArgsConstructor", "AllArgsConstructor", 
        "Getter", "Setter", "ToString",
        "Schema", "JsonPropertyOrder", "JsonIgnoreProperties"
    }
    if any(a in annotations for a in dto_indicators):
        return "DTO"
    
    # 6. 通用元件判斷 (放在較後方，避免過早攔截)
    if "Component" in annotations:
        return "REPOSITORY" # 或根據你的需求歸類為 COMPONENT
    
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
        # print("Classified as ENTITY")
        return extract_entity_features(code_content)
    
    elif classification == "DTO":
        # print("Classified as DTO")
        return extract_dto_features(code_content)
        
    elif classification == "CONTROLLER" or classification == "SERVICE":
        # print("Classified as CONTROLLER or SERVICE")
        return extract_class_features(code_content, True)
        
    elif classification == "REPOSITORY":
        # print("Classified as REPOSITORY")
        return extract_repository_features(code_content)
        
    else:
        # 其他一般的 POJO 或 Utility 類別
        # print("Classified as UNKNOWN")
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
        (class_declaration
        (modifiers
            [
                (marker_annotation name: (identifier) @class.annotation)
                (annotation name: (identifier) @class.annotation)
            ] *
        )
        name: (identifier) @class.name
        ) @class.definition
        
        (field_declaration
            type: [
                (type_identifier) @dep.type
                (generic_type) @dep.type
            ]
            declarator: (variable_declarator name: (identifier) @dep.name)
        ) @class.dependency

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
                            (string_literal (string_fragment) @path.class)
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
                            (string_literal (string_fragment) @path.method)
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
    # query = Query(
    #     JAVA_LANGUAGE,
    #     """
    #     (class_declaration
    #         name: (identifier) @entity.name
    #         body: (class_body
    #             [
    #                 (field_declaration
    #                     (modifiers
    #                         [
    #                             (marker_annotation name: (identifier) @field.annotation)
    #                             (annotation name: (identifier) @field.annotation)
    #                         ]
    #                     )*
    #                     type: [
    #                         (type_identifier) @field.type
    #                         (generic_type) @field.type
    #                     ]
    #                     declarator: (variable_declarator
    #                     name: (identifier) @field.name)
    #                 ) @entity.field

    #                 (enum_declaration
    #                     name: (identifier) @enum.name
    #                     body: (enum_body
    #                         (enum_constant name: (identifier) @enum.member)*
    #                     )
    #                 ) @entity.enum
    #             ]
    #         )
    #     )
    #     """
    # )
    
    # === test qeury ===
    query = Query(
        JAVA_LANGUAGE,
        """
        (class_declaration
            [
                (modifiers
                    [
                        (marker_annotation name: (identifier) @entity.annotation)
                        (annotation name: (identifier) @entity.annotation)
                    ]
                )
            ]*
            
            name: (identifier) @entity.name
            
            superclass: (superclass 
                (type_identifier) @entity.superclass
            )?
            
            body: (class_body
                [
                    (field_declaration
                        [
                            (modifiers
                                [
                                    (marker_annotation name: (identifier) @field.annotation)
                                    (annotation name: (identifier) @field.annotation)
                                ]*
                            )
                        ]?
                        type: [
                            (type_identifier) @field.type
                            (generic_type) @field.type
                        ]
                        declarator: (variable_declarator
                            name: (identifier) @field.name
                        )
                    ) @entity.field
                    
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


def extract_dto_features(code_content: str):
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    # print(prettify_sexp(str(root_node)))
    
    query = Query(
        JAVA_LANGUAGE,
        """
        (class_declaration
            (modifiers
                (marker_annotation
                name: (identifier) @class.annotation))?
            name: (identifier) @dto.name
        
            superclass: (superclass
                (type_identifier) @dto.parent)?

            body: (class_body
                (field_declaration
                    (modifiers
                        [
                        (annotation
                            name: (identifier) @field.annotation
                            arguments: (annotation_argument_list)? )
                        (marker_annotation
                            name: (identifier) @field.annotation)
                        ]
                    )?
                    type: [
                        (type_identifier) @field.type
                        (generic_type) @field.type
                    ]
                    declarator: (variable_declarator
                        name: (identifier) @field.name
                        value: (_)? @field.default_value
                    )
                ) @field.entry

                (constructor_declaration
                    name: (identifier) @constructor.name
                    parameters: (formal_parameters
                        (formal_parameter
                            type: (_) @param.type
                            name: (identifier) @param.name) @constructor.param
                    )
                )?
            )
        )
        """
    )

    query_cursor = QueryCursor(query)
    matches = query_cursor.matches(tree.root_node)
    # print(matches)

    return process_dto_features(matches, code_bytes)

def extract_repository_features(code_content: str):
    code_bytes = bytes(code_content, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    # print(prettify_sexp(str(root_node)))
    
    query = Query(
        JAVA_LANGUAGE,
        """
        (interface_declaration
            (modifiers
                [
                (marker_annotation 
                    name: (identifier) @repo.anno)
                (annotation
                    name: (identifier) @repo.anno)
                ]?
            )
            name: (identifier) @repo.name

            (extends_interfaces
                (type_list
                    (generic_type
                        (type_identifier) @repo.base_interface
                        (#match? @repo.base_interface "Repository|JpaRepository|CrudRepository|PagingAndSortingRepository")
                        (type_arguments
                        [
                            (type_identifier) @repo.managed_entity
                            (generic_type) @repo.managed_entity
                        ]
                            (type_identifier) @repo.id_type
                        )
                    )
                )
            )?

        ) @repo.definition

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
    
    if (matches is None) or (len(matches) == 0):
        return None
    
    return process_repository_features(matches, code_bytes)


