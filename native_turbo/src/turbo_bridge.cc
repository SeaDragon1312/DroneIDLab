// Derived from proto17/dji_droneid cpp/remove_turbo.cc, commit 7c6dddad, MIT.
// Memory-buffer ABI instead of files/stdout. Same bit LUT, D/E/rv, iterations,
// TurboFEC calls and CRC++ CRC24. No systematic-only fallback.
// TurboFEC is GPL-3.0-or-later; see native_turbo/third_party/*/LICENSE.
#define CRCPP_INCLUDE_ESOTERIC_CRC_DEFINITIONS
#include <CRC.h>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <vector>
extern "C" {
#include <turbofec/rate_match.h>
#include <turbofec/turbo.h>
}
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
constexpr int E = 7200, D = 1412, K = 1408, BYTES = 176;

static int unmatch(const uint8_t *bits, size_t count, std::vector<int8_t> (&d)[3]) {
    if (!bits || count != E) return -2;
    int8_t bit_value_lut[2] = {-63, 63}; // exact proto17 mapping
    std::vector<int8_t> input(E);
    for (size_t i=0;i<count;i++) {
        if (bits[i] != 0 && bits[i] != 1) return -3;
        input[i] = bit_value_lut[bits[i]];
    }
    for (auto &stream:d) stream.resize(D);
    auto *matcher=lte_rate_matcher_alloc();
    if (!matcher) return -4;
    lte_rate_matcher_io io = {D,E,{d[0].data(),d[1].data(),d[2].data()},input.data()};
    const int status=lte_rate_match_rv(matcher,&io,0);
    lte_rate_matcher_free(matcher);
    return status ? -5 : 0;
}

API int droneid_turbo_abi_version() { return 1; }

// Return 0 = FEC executed and CRC24 pass; 1 = FEC executed but CRC24 fail.
// Negative return is a backend/input error: output must not be consumed.
// Optional diagnostic streams are copied BEFORE turbo_unterm mutates them.
API int droneid_turbo_decode(const uint8_t *bits, size_t count,
                            uint8_t *output, size_t output_size,
                            uint32_t *crc24_residue, int8_t *diagnostic_streams) {
    if (!output || output_size != BYTES || !crc24_residue) return -2;
    std::vector<int8_t> d[3];
    const int rc=unmatch(bits,count,d);
    if (rc) return rc;
    if (diagnostic_streams)
        for (int i=0;i<3;i++) std::memcpy(diagnostic_streams+i*D,d[i].data(),D);
    auto *decoder=alloc_tdec();
    if (!decoder) return -4;
    const int status=lte_turbo_decode(decoder,K,4,output,d[0].data(),d[1].data(),d[2].data());
    free_tdec(decoder);
    if (status) return -6;
    *crc24_residue=CRC::Calculate(output,BYTES,CRC::CRC_24_LTEA());
    return *crc24_residue==0 ? 0 : 1;
}

// Test helpers, never called as an alternate production decoder.
API int droneid_test_decode_streams(const int8_t *streams, uint8_t *output) {
    if (!streams || !output) return -2;
    std::vector<int8_t> d[3];
    for (int i=0;i<3;i++) d[i].assign(streams+i*D,streams+(i+1)*D);
    auto *decoder=alloc_tdec();
    if (!decoder) return -4;
    int rc=lte_turbo_decode(decoder,K,4,output,d[0].data(),d[1].data(),d[2].data());
    free_tdec(decoder);return rc;
}

// Encode an already obtained 176-byte block, preserving its original CRC24.
// For controlled offline round-trip/error tests only; no waveform or RF output.
API int droneid_test_encode(const uint8_t *bytes, size_t size, uint8_t *coded) {
    if (!bytes || size!=BYTES || !coded) return -2;
    std::vector<uint8_t> input(K), d0(D), d1(D), d2(D);
    for (int i=0;i<K;i++) input[i]=(bytes[i/8]>>(7-i%8))&1;
    lte_turbo_code code={2,4,K,11,13}; // same as proto17 add_turbo.cc (013 / 015 octal)
    int rc=lte_turbo_encode(&code,input.data(),d0.data(),d1.data(),d2.data());
    if (rc != 3*D) return -7;
    auto *matcher=lte_rate_matcher_alloc();
    if (!matcher) return -4;
    lte_rate_matcher_io io={D,E,{(int8_t*)d0.data(),(int8_t*)d1.data(),(int8_t*)d2.data()},(int8_t*)coded};
    rc=lte_rate_match_fw(matcher,&io,0);
    lte_rate_matcher_free(matcher);return rc;
}
