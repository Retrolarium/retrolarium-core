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
    src/project/build_plan.cpp
    src/megadrive/enigma.cpp
    src/audio/midi.cpp
    src/fds/fds.cpp
    src/megadrive/enigma_encode.cpp
    src/nes/ines.cpp
    src/megadrive/nemesis.cpp
    src/nes/nametable.cpp
    src/nes/palette.cpp
    src/nes/ppu_packets.cpp
    src/nes/text.cpp
    src/nes/tiles.cpp
    src/megadrive/nemesis_encode.cpp
    src/project/resource_source.cpp
    src/hash/sha1.cpp
    src/hash/sha256.cpp
    src/project/game_profile.cpp
    src/project/studio_project.cpp
    src/data/value.cpp
    src/data/value_json.cpp
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
    add_executable(retrolarium-core-toml-smoke-tests tests/data/toml_smoke_test.cpp)
    target_link_libraries(retrolarium-core-toml-smoke-tests PRIVATE retrolarium_toml)
    retrolarium_core_enable_warnings(retrolarium-core-toml-smoke-tests)
    add_test(NAME core.toml_smoke COMMAND retrolarium-core-toml-smoke-tests)

    add_executable(retrolarium-core-studio-project-tests
        tests/project/studio_project_test.cpp)
    target_link_libraries(retrolarium-core-studio-project-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(
        retrolarium-core-studio-project-tests)
    add_test(NAME core.studio_project_parity
        COMMAND retrolarium-core-studio-project-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/project/studio_project_golden.txt
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/project/studio_projects
    )

    add_executable(retrolarium-core-game-profile-tests
        tests/project/game_profile_test.cpp)
    target_link_libraries(retrolarium-core-game-profile-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-game-profile-tests)
    add_test(NAME core.game_profile_parity
        COMMAND retrolarium-core-game-profile-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/project/game_profile_golden.txt
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/project/game_profiles
    )

    add_executable(retrolarium-core-sha256-tests tests/hash/sha256_test.cpp)
    target_link_libraries(retrolarium-core-sha256-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-sha256-tests)
    add_test(NAME core.sha256 COMMAND retrolarium-core-sha256-tests)

    add_executable(retrolarium-core-sha1-tests tests/hash/sha1_test.cpp)
    target_link_libraries(retrolarium-core-sha1-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-sha1-tests)
    add_test(NAME core.sha1 COMMAND retrolarium-core-sha1-tests)

    add_executable(retrolarium-core-fds-tests tests/fds/fds_test.cpp)
    target_link_libraries(retrolarium-core-fds-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-fds-tests)
    add_test(NAME core.fds_parity
        COMMAND retrolarium-core-fds-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/fds/fds_golden.txt
    )

    add_executable(retrolarium-core-resource-source-tests
        tests/project/resource_source_test.cpp)
    target_link_libraries(retrolarium-core-resource-source-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(
        retrolarium-core-resource-source-tests)
    add_test(NAME core.resource_source_parity
        COMMAND retrolarium-core-resource-source-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/project/resource_source_golden.txt
    )

    add_executable(retrolarium-core-ines-tests tests/nes/ines_test.cpp)
    target_link_libraries(retrolarium-core-ines-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-ines-tests)
    add_test(NAME core.ines_parity
        COMMAND retrolarium-core-ines-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes/ines_golden.txt
    )

    add_executable(retrolarium-core-nemesis-tests tests/megadrive/nemesis_test.cpp)
    target_link_libraries(retrolarium-core-nemesis-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nemesis-tests)
    add_test(NAME core.nemesis_parity
        COMMAND retrolarium-core-nemesis-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/megadrive/nemesis_golden.txt
    )

    add_executable(retrolarium-core-enigma-tests tests/megadrive/enigma_test.cpp)
    target_link_libraries(retrolarium-core-enigma-tests PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-enigma-tests)
    add_test(NAME core.enigma_parity
        COMMAND retrolarium-core-enigma-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/megadrive/enigma_golden.txt
    )

    add_executable(retrolarium-core-nes-tiles-tests
        tests/nes/tiles_test.cpp)
    target_link_libraries(retrolarium-core-nes-tiles-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-tiles-tests)
    add_test(NAME core.nes_tiles_parity
        COMMAND retrolarium-core-nes-tiles-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes/tiles_golden.txt
    )

    add_executable(retrolarium-core-nes-surfaces-tests
        tests/nes/surfaces_test.cpp)
    target_link_libraries(retrolarium-core-nes-surfaces-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-surfaces-tests)
    add_test(NAME core.nes_surfaces_parity
        COMMAND retrolarium-core-nes-surfaces-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes/surfaces_golden.txt
    )

    add_executable(retrolarium-core-nes-ppu-packets-tests
        tests/nes/ppu_packets_test.cpp)
    target_link_libraries(retrolarium-core-nes-ppu-packets-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-ppu-packets-tests)
    add_test(NAME core.nes_ppu_packets_parity
        COMMAND retrolarium-core-nes-ppu-packets-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes/ppu_packets_golden.txt
    )

    add_executable(retrolarium-core-midi-tests
        tests/audio/midi_test.cpp)
    target_link_libraries(retrolarium-core-midi-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-midi-tests)
    add_test(NAME core.midi_parity
        COMMAND retrolarium-core-midi-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/audio/midi_golden.txt
    )

    add_executable(retrolarium-core-nes-text-tests
        tests/nes/text_test.cpp)
    target_link_libraries(retrolarium-core-nes-text-tests
        PRIVATE retrolarium_core)
    retrolarium_core_enable_warnings(retrolarium-core-nes-text-tests)
    add_test(NAME core.nes_text_parity
        COMMAND retrolarium-core-nes-text-tests
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/nes/text_golden.txt
    )
endif()
