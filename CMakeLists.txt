cmake_minimum_required(VERSION 3.21)

# retrolarium_core is deliberately standalone: no Qt, no dependency on the
# application tree. The same sources produce the rlcore executable that the
# Python Kit runs as a pinned tool and the static library that the Qt
# application links directly. Keeping this buildable on its own is what makes
# extracting it into its own repository cheap later.
project(
    RetrolariumCore
    VERSION 0.5.0
    DESCRIPTION "Mega Drive compressions shared by Retrolarium and its Kit"
    LANGUAGES CXX
)

# CTest (and its BUILD_TESTING option) only when the core is the project being
# built: the Studio adds it with add_subdirectory and runs its own tests.
if(PROJECT_IS_TOP_LEVEL)
    include(CTest)
endif()

option(RETROLARIUM_CORE_BUILD_CLI "Build the rlcore executable" ON)
option(RETROLARIUM_CORE_BUILD_TESTS "Build retrolarium_core tests" ON)
option(RETROLARIUM_SANITIZE "Build the core, rlcore and the tests with ASan and UBSan (GCC or Clang)" OFF)
option(RETROLARIUM_FUZZ "Build the libFuzzer targets for the Nemesis and Enigma decoders (Clang)" OFF)

if(RETROLARIUM_SANITIZE AND MSVC)
    message(FATAL_ERROR "RETROLARIUM_SANITIZE needs GCC or Clang")
endif()
if(RETROLARIUM_FUZZ AND NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    message(FATAL_ERROR "RETROLARIUM_FUZZ needs Clang, whose libFuzzer provides the fuzzers' main")
endif()

# Warnings for every target of the core, and the sanitizers when asked for.
function(retrolarium_core_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive- /utf-8)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    if(RETROLARIUM_SANITIZE)
        target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(${target} PRIVATE -fsanitize=address,undefined)
    endif()
endfunction()

add_library(retrolarium_core STATIC
    src/megadrive/enigma.cpp
    src/megadrive/enigma_encode.cpp
    src/megadrive/nemesis.cpp
    src/megadrive/nemesis_encode.cpp
)
add_library(retrolarium::core ALIAS retrolarium_core)

# One version for the library, rlcore and the Python package: the header
# rlcore prints it from is generated from project(VERSION) above.
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/version.hpp.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/retrolarium/core/version.hpp
    @ONLY
)

target_include_directories(retrolarium_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
)
target_compile_features(retrolarium_core PUBLIC cxx_std_17)
retrolarium_core_enable_warnings(retrolarium_core)

if(RETROLARIUM_CORE_BUILD_CLI)
    add_executable(rlcore cli/main.cpp)
    target_link_libraries(rlcore PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(rlcore)
endif()

if(RETROLARIUM_CORE_BUILD_TESTS AND BUILD_TESTING)
    # One registration supplies CTest and the portable Python runner.
    function(retrolarium_core_add_test name target)
        cmake_parse_arguments(TEST "" "EXPECTED_EXIT" "ARGS" ${ARGN})
        if(NOT DEFINED TEST_EXPECTED_EXIT)
            set(TEST_EXPECTED_EXIT 0)
        endif()
        set(command_arguments)
        set(json_arguments)
        foreach(argument IN LISTS TEST_ARGS)
            if(argument MATCHES "^repo:(.*)$")
                list(APPEND command_arguments "${CMAKE_CURRENT_SOURCE_DIR}/${CMAKE_MATCH_1}")
            elseif(argument MATCHES "^bin:(.*)$")
                list(APPEND command_arguments "${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_MATCH_1}")
            else()
                list(APPEND command_arguments "${argument}")
            endif()
            string(REPLACE "\\" "\\\\" escaped "${argument}")
            string(REPLACE "\"" "\\\"" escaped "${escaped}")
            list(APPEND json_arguments "\"${escaped}\"")
        endforeach()
        string(JOIN ", " json_arguments ${json_arguments})
        set(entry "  {\"name\": \"${name}\", \"program\": \"$<TARGET_FILE_NAME:${target}>\", \"arguments\": [${json_arguments}], \"expected_exit\": ${TEST_EXPECTED_EXIT}}")
        set_property(GLOBAL APPEND PROPERTY retrolarium_core_test_entries "${entry}")
        if(TEST_EXPECTED_EXIT EQUAL 0)
            add_test(NAME ${name} COMMAND $<TARGET_FILE:${target}> ${command_arguments})
        else()
            string(JOIN "|" packed_arguments ${command_arguments})
            add_test(NAME ${name}
                COMMAND ${CMAKE_COMMAND}
                    -DRLCORE=$<TARGET_FILE:${target}>
                    "-DARGUMENTS=${packed_arguments}"
                    -DEXPECTED=${TEST_EXPECTED_EXIT}
                    -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/cli/expect_exit.cmake
            )
        endif()
    endfunction()

    foreach(codec IN ITEMS nemesis enigma)
        add_executable(retrolarium-core-${codec}-tests tests/megadrive/${codec}_test.cpp)
        target_link_libraries(retrolarium-core-${codec}-tests PRIVATE retrolarium_core)
        retrolarium_core_enable_warnings(retrolarium-core-${codec}-tests)
        retrolarium_core_add_test(core.${codec}_parity retrolarium-core-${codec}-tests
            ARGS repo:tests/fixtures/megadrive/${codec}_golden.txt)
    endforeach()

    if(RETROLARIUM_CORE_BUILD_CLI)
        foreach(case IN ITEMS "suffix|12abc|2" "range|70000|2" "sign|-1|2" "hex|0x10|3" "decimal|65535|3")
            string(REPLACE "|" ";" fields "${case}")
            list(GET fields 0 name)
            list(GET fields 1 tile)
            list(GET fields 2 expected)
            retrolarium_core_add_test(core.cli_base_tile_${name} rlcore
                ARGS enigma decompress bin:no-such-input.eni bin:unused-output.bin ${tile}
                EXPECTED_EXIT ${expected})
        endforeach()
    endif()
    get_property(core_tests GLOBAL PROPERTY retrolarium_core_test_entries)
    string(JOIN ",\n" core_tests ${core_tests})
    file(GENERATE OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/tests.json CONTENT "[\n${core_tests}\n]\n")
endif()

# Fuzz targets: each compiles its codec's sources itself, instrumented for
# libFuzzer, so the library and rlcore stay as they are. Run one with a seed
# corpus from the golden streams, e.g.
#   python fuzz/seed_corpus.py tests/fixtures/megadrive/nemesis_golden.txt seeds/nemesis
#   build/retrolarium-core-fuzz-nemesis -max_total_time=60 seeds/nemesis
if(RETROLARIUM_FUZZ)
    foreach(codec IN ITEMS nemesis enigma)
        set(target retrolarium-core-fuzz-${codec})
        add_executable(${target}
            fuzz/${codec}_decode.cpp
            src/megadrive/${codec}.cpp
            src/megadrive/${codec}_encode.cpp
        )
        target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
        target_compile_features(${target} PRIVATE cxx_std_17)
        target_compile_options(${target} PRIVATE -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer)
        target_link_options(${target} PRIVATE -fsanitize=fuzzer,address,undefined)
    endforeach()
endif()
