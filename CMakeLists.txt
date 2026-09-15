cmake_minimum_required(VERSION 3.21)

# retrolarium_core is deliberately standalone: no Qt, no dependency on the
# application tree. The same sources produce the rlcore executable that the
# Python Kit ships as a pinned tool and the static library that the Qt
# application links directly. Keeping this buildable on its own is what makes
# extracting it into its own repository cheap later.
project(
    RetrolariumCore
    VERSION 0.1.0
    DESCRIPTION "Container, compression and tile primitives shared by Retrolarium and its Kit"
    LANGUAGES CXX
)

include(CTest)

option(RETROLARIUM_CORE_BUILD_CLI "Build the rlcore executable" ON)
# Embedded in the application build the core still tests itself, so the
# cross-language parity corpus runs in the same sweep as everything else.
option(RETROLARIUM_CORE_BUILD_TESTS "Build retrolarium_core tests" ON)

function(retrolarium_core_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive-)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endfunction()

add_library(retrolarium_core STATIC
    src/enigma.cpp
    src/enigma_encode.cpp
    src/ines.cpp
    src/nemesis.cpp
    src/sha256.cpp
)
add_library(retrolarium::core ALIAS retrolarium_core)

target_include_directories(retrolarium_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_compile_features(retrolarium_core PUBLIC cxx_std_17)
retrolarium_core_enable_warnings(retrolarium_core)

if(RETROLARIUM_CORE_BUILD_CLI)
    add_executable(rlcore cli/main.cpp)
    target_link_libraries(rlcore PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(rlcore)
endif()

if(RETROLARIUM_CORE_BUILD_TESTS AND BUILD_TESTING)
    add_executable(retrolarium-core-sha256-tests tests/sha256_test.cpp)
    target_link_libraries(retrolarium-core-sha256-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-sha256-tests)
    add_test(NAME core.sha256 COMMAND retrolarium-core-sha256-tests)

    add_executable(retrolarium-core-ines-golden-tests tests/ines_golden_test.cpp)
    target_link_libraries(retrolarium-core-ines-golden-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-ines-golden-tests)
    add_test(NAME core.ines_parity
        COMMAND retrolarium-core-ines-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/ines_golden.txt
    )

    add_executable(retrolarium-core-nemesis-golden-tests tests/nemesis_golden_test.cpp)
    target_link_libraries(retrolarium-core-nemesis-golden-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nemesis-golden-tests)
    add_test(NAME core.nemesis_parity
        COMMAND retrolarium-core-nemesis-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nemesis_golden.txt
    )

    add_executable(retrolarium-core-enigma-golden-tests tests/enigma_golden_test.cpp)
    target_link_libraries(retrolarium-core-enigma-golden-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-enigma-golden-tests)
    add_test(NAME core.enigma_parity
        COMMAND retrolarium-core-enigma-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/enigma_golden.txt
    )
endif()
