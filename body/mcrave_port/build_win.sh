#!/usr/bin/env bash
# Cross-compile the patched McRave (third_party/mcrave) as a 32-bit Windows BWAPI 4.4.0 module
# (build/mcrave_win/McRave.dll) with clang-cl + lld-link on Linux. Used by the Pluto lane
# (docs/setup_pluto_lane.md): StarCraft 1.16.1 under Wine, where only MSVC-ABI DLLs load.
#
# Prerequisites (all git-ignored, see docs/setup_pluto_lane.md):
#   third_party/xwin/splat            MSVC CRT + Windows SDK (xwin --accept-license splat)
#   third_party/bwapi440/Release_Binary  BWAPI 4.4.0 SDK (include/ + BWAPILIB/Source, built here)
#   third_party/mcrave                McRave @7d1719a with body/patches/mcrave applied
#   clang-cl + lld-link (LLVM 18)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SPLAT="${SPLAT:-$ROOT/third_party/xwin/splat}"
BWAPI="${BWAPI_SDK:-$ROOT/third_party/bwapi440/Release_Binary}"
MCRAVE="${MCRAVE_ROOT:-$ROOT/third_party/mcrave}"
OUT="${OUT:-$ROOT/build/mcrave_win}"
JOBS="${JOBS:-$(nproc)}"
CLANG_CL="${CLANG_CL:-$(command -v clang-cl || echo /usr/lib/llvm-18/bin/clang-cl)}"
LLD_LINK="${LLD_LINK:-lld-link}"

[ -d "$SPLAT/crt/include" ] || { echo "missing $SPLAT (run xwin splat)" >&2; exit 1; }
[ -f "$BWAPI/include/BWAPI.h" ] || { echo "missing BWAPI SDK at $BWAPI" >&2; exit 1; }
[ -f "$MCRAVE/Source/McRave/Main/Sidecar.cpp" ] || { echo "McRave not patched (apply_patches.sh)" >&2; exit 1; }

mkdir -p "$OUT/obj/bwapilib" "$OUT/obj/mcrave"
CXXFLAGS=(--target=i686-pc-windows-msvc /std:c++17 /O2 /MT /EHsc /GR /W0 /c
  /DNOMINMAX /DWIN32 /DNDEBUG /D_WINDOWS /D_USRDLL /DEXAMPLEAIMODULE_EXPORTS /D_CRT_SECURE_NO_WARNINGS /D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH
  /imsvc "$SPLAT/crt/include" /imsvc "$SPLAT/sdk/include/ucrt" /imsvc "$SPLAT/sdk/include/um" /imsvc "$SPLAT/sdk/include/shared"
  -fms-compatibility-version=19.29 -Wno-everything)
INC=(/I "$BWAPI/include" /I "$ROOT/body/sidecar_client" /I "$MCRAVE/Source/BWEB" /I "$MCRAVE/Source/BWEM" /I "$MCRAVE/Source/Horizon" /I "$MCRAVE/Source/McRave")

# Per-TU driver (skips up-to-date objects); run in parallel with xargs below.
cat > "$OUT/cc1.sh" <<DRV
#!/usr/bin/env bash
set -e
src="\$1"; obj="\$2"
[ -f "\$obj" ] && [ ! "\$src" -nt "\$obj" ] && exit 0
exec "$CLANG_CL" $(printf '%q ' "${CXXFLAGS[@]}") $(printf '%q ' "${INC[@]}") "/Fo\$obj" "\$src"
DRV
chmod +x "$OUT/cc1.sh"

# BWAPILIB (the static part of BWAPI every module links; the SDK ships it as source), then McRave:
# the vcxproj set (Source/{BWEB,BWEM,Horizon,McRave}/**/*.cpp incl. Dll.cpp, minus winutils.cpp) + Sidecar.cpp (patch 0006)
list=()
# UnitCommand.cpp lives one level up from Source/ (as in BWAPILIB.vcxproj)
for f in "$BWAPI"/BWAPILIB/Source/*.cpp "$BWAPI"/BWAPILIB/UnitCommand.cpp; do list+=("$f" "$OUT/obj/bwapilib/$(basename "${f%.cpp}").obj"); done
while IFS= read -r f; do
  rel="${f#$MCRAVE/Source/}"; list+=("$f" "$OUT/obj/mcrave/$(echo "${rel%.cpp}" | tr '/' '_').obj")
done < <(find "$MCRAVE/Source/McRave" "$MCRAVE/Source/BWEM" "$MCRAVE/Source/BWEB" "$MCRAVE/Source/Horizon" -name '*.cpp' | grep -v '/BWEM/winutils\.cpp$' | sort)   # winutils: BWEM_USE_WINUTILS=0 (patch 0001), TU does not compile standalone

echo "compiling $(( ${#list[@]} / 2 )) translation units with $JOBS jobs -> $OUT"
printf '%s\n' "${list[@]}" | xargs -n2 -P"$JOBS" "$OUT/cc1.sh"

echo "linking McRave.dll"
"$LLD_LINK" /DLL /OUT:"$OUT/McRave.dll" /MACHINE:X86 /SUBSYSTEM:WINDOWS /NOLOGO \
  /LIBPATH:"$SPLAT/crt/lib/x86" /LIBPATH:"$SPLAT/sdk/lib/um/x86" /LIBPATH:"$SPLAT/sdk/lib/ucrt/x86" \
  "$OUT"/obj/bwapilib/*.obj "$OUT"/obj/mcrave/*.obj ws2_32.lib user32.lib kernel32.lib
ls -la "$OUT/McRave.dll"
# Loader check binary (tools/win_loadtest): wine build/mcrave_win/loadtest.exe build/mcrave_win/McRave.dll
"$CLANG_CL" "${CXXFLAGS[@]}" "/Fo$OUT/obj/loadtest.obj" "$ROOT/tools/win_loadtest/loadtest.cpp"
"$LLD_LINK" /OUT:"$OUT/loadtest.exe" /MACHINE:X86 /SUBSYSTEM:CONSOLE /NOLOGO /LIBPATH:"$SPLAT/crt/lib/x86" /LIBPATH:"$SPLAT/sdk/lib/um/x86" /LIBPATH:"$SPLAT/sdk/lib/ucrt/x86" "$OUT/obj/loadtest.obj" kernel32.lib
