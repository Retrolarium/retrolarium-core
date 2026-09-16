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

# Vendored, see third_party/README.md.
add_library(retrolarium_toml INTERFACE)
target_include_directories(retrolarium_toml
    INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/third_party/toml11)
target_compile_features(retrolarium_toml INTERFACE cxx_std_17)

# GCC below 9 keeps the filesystem library in its own archive, and ships it as
# the experimental TS rather than std::filesystem.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 9)
    target_link_libraries(retrolarium_toml INTERFACE stdc++fs)
endif()

add_library(retrolarium_json INTERFACE)
# Included as <nlohmann/json.hpp>: the bare name is too generic to put on
# an include path.
target_include_directories(retrolarium_json
    INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
target_compile_features(retrolarium_json INTERFACE cxx_std_17)

add_library(retrolarium_core STATIC
    src/build_plan.cpp
    src/enigma.cpp
    src/fds.cpp
    src/enigma_encode.cpp
    src/ines.cpp
    src/nemesis.cpp
    src/nes_nametable.cpp
    src/nes_palette.cpp
    src/nes_ppu_packets.cpp
    src/nes_text.cpp
    src/nes_tiles.cpp
    src/nemesis_encode.cpp
    src/resource_source.cpp
    src/sha1.cpp
    src/sha256.cpp
    src/game_profile.cpp
    src/studio_project.cpp
    src/value.cpp
    src/value_json.cpp
)
add_library(retrolarium::core ALIAS retrolarium_core)
# PRIVATE: the TOML parser is an implementation detail of one source file.
target_link_libraries(retrolarium_core PRIVATE retrolarium_toml retrolarium_json)

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
    add_executable(retrolarium-core-toml-smoke-tests tests/toml_smoke_test.cpp)
    target_link_libraries(retrolarium-core-toml-smoke-tests PRIVATE retrolarium_toml)
    retrolarium_core_enable_warnings(retrolarium-core-toml-smoke-tests)
    add_test(NAME core.toml_smoke COMMAND retrolarium-core-toml-smoke-tests)

    add_executable(retrolarium-core-studio-project-golden-tests
        tests/studio_project_golden_test.cpp)
    target_link_libraries(retrolarium-core-studio-project-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(
        retrolarium-core-studio-project-golden-tests)
    add_test(NAME core.studio_project_parity
        COMMAND retrolarium-core-studio-project-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/studio_project_golden.txt
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/studio_projects
    )

    add_executable(retrolarium-core-game-profile-golden-tests
        tests/game_profile_golden_test.cpp)
    target_link_libraries(retrolarium-core-game-profile-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-game-profile-golden-tests)
    add_test(NAME core.game_profile_parity
        COMMAND retrolarium-core-game-profile-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/game_profile_golden.txt
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/game_profiles
    )

    add_executable(retrolarium-core-sha256-tests tests/sha256_test.cpp)
    target_link_libraries(retrolarium-core-sha256-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-sha256-tests)
    add_test(NAME core.sha256 COMMAND retrolarium-core-sha256-tests)

    add_executable(retrolarium-core-sha1-tests tests/sha1_test.cpp)
    target_link_libraries(retrolarium-core-sha1-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-sha1-tests)
    add_test(NAME core.sha1 COMMAND retrolarium-core-sha1-tests)

    add_executable(retrolarium-core-fds-golden-tests tests/fds_golden_test.cpp)
    target_link_libraries(retrolarium-core-fds-golden-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-fds-golden-tests)
    add_test(NAME core.fds_parity
        COMMAND retrolarium-core-fds-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/fds_golden.txt
    )

    add_executable(retrolarium-core-resource-source-golden-tests
        tests/resource_source_golden_test.cpp)
    target_link_libraries(retrolarium-core-resource-source-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(
        retrolarium-core-resource-source-golden-tests)
    add_test(NAME core.resource_source_parity
        COMMAND retrolarium-core-resource-source-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/resource_source_golden.txt
    )

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

    add_executable(retrolarium-core-nes-tiles-golden-tests
        tests/nes_tiles_golden_test.cpp)
    target_link_libraries(retrolarium-core-nes-tiles-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-tiles-golden-tests)
    add_test(NAME core.nes_tiles_parity
        COMMAND retrolarium-core-nes-tiles-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes_tiles_golden.txt
    )

    add_executable(retrolarium-core-nes-surfaces-golden-tests
        tests/nes_surfaces_golden_test.cpp)
    target_link_libraries(retrolarium-core-nes-surfaces-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-surfaces-golden-tests)
    add_test(NAME core.nes_surfaces_parity
        COMMAND retrolarium-core-nes-surfaces-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes_surfaces_golden.txt
    )

    add_executable(retrolarium-core-nes-ppu-packets-golden-tests
        tests/nes_ppu_packets_golden_test.cpp)
    target_link_libraries(retrolarium-core-nes-ppu-packets-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-ppu-packets-golden-tests)
    add_test(NAME core.nes_ppu_packets_parity
        COMMAND retrolarium-core-nes-ppu-packets-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes_ppu_packets_golden.txt
    )

    add_executable(retrolarium-core-nes-text-golden-tests
        tests/nes_text_golden_test.cpp)
    target_link_libraries(retrolarium-core-nes-text-golden-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-text-golden-tests)
    add_test(NAME core.nes_text_parity
        COMMAND retrolarium-core-nes-text-golden-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes_text_golden.txt
    )
endif()
