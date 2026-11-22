# Runs rlcore with ARGUMENTS (separated by |) and fails unless it exits with
# EXPECTED:
#   cmake -DRLCORE=<rlcore> -DARGUMENTS=enigma|decompress|... -DEXPECTED=2 -P expect_exit.cmake
string(REPLACE "|" ";" arguments "${ARGUMENTS}")
execute_process(
    COMMAND "${RLCORE}" ${arguments}
    RESULT_VARIABLE result
    OUTPUT_VARIABLE output
    ERROR_VARIABLE error
)
if(NOT result STREQUAL EXPECTED)
    message(FATAL_ERROR "rlcore ${ARGUMENTS} exited with ${result}, expected ${EXPECTED}\n${output}${error}")
endif()
