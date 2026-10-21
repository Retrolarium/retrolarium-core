cmake_minimum_required(VERSION 3.21)

# retrolarium_core is deliberately standalone: no Qt, no dependency on the
# application tree. The same sources produce the rlcore executable that the
# Python Kit runs as a pinned tool and the static library that the Qt
# application links directly. Keeping this buildable on its own is what makes
# extracting it into its own repository cheap later.
project(
    RetrolariumCore
    VERSION 0.1.0
    DESCRIPTION "Mega Drive compressions shared by Retrolarium and its Kit"
    LANGUAGES CXX
)

include(CTest)

option(RETROLARIUM_CORE_BUILD_CLI "Build the rlcore executable" ON)
option(RETROLARIUM_CORE_BUILD_TESTS "Build retrolarium_core tests" ON)

function(retrolarium_core_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive-)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endfunction()

add_library(retrolarium_core STATIC
    src/megadrive/enigma.cpp
    src/megadrive/enigma_encode.cpp
    src/megadrive/nemesis.cpp
    src/megadrive/nemesis_encode.cpp
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
endif()
