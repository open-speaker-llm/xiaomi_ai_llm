// SPDX-License-Identifier: LGPL-3.0-only
// Rust adaptation of rany2/edge-tts src/edge_tts/drm.py at
// bd44c1d1aaebdc1db7f47456ee12431b42ec7cac. See ../NOTICE.edge-tts.md.
// All arithmetic is explicitly modulo 2^32, including in debug builds.

const INITIAL: [u32; 8] = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
];
const RESUME_STATE: [u32; 8] = [
    0xFD9FBEA2, 0x91243CE7, 0xBE499094, 0xCD2E1E0A, 0x6C006F49, 0x04BD35AB, 0xFEB0A7E4, 0x03EFFBD2,
];
const SCHEDULE: [u32; 14] = [
    0xEB24BF9E, 0x1558691F, 0xA0C09EE2, 0x0CFA32BA, 0xA622EE8C, 0xD1DD9491, 0xC0DD25A0, 0xF9E70AB6,
    0xF0C31573, 0x7058CE4E, 0x7188E606, 0x00E5AB33, 0xD258B060, 0x72766564,
];
const K: [u32; 64] = [
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
    0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3, 0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
    0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
    0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13, 0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85,
    0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3,
    0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208, 0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
];
const ADJUSTMENT: u32 = 0xC9DC06A7;
const COEFFICIENTS: [(u32, u32); 14] = [
    (0xE82E91B1, 0xB32700D0),
    (0x44DE24C6, 0x88DFF51D),
    (0x3BEB65BC, 0x29514038),
    (0xC89C5933, 0xB328CBDF),
    (0x8D1EC211, 0xD405B4D5),
    (0x314EF5D5, 0x26E55F3C),
    (0xE92491B1, 0x607801C6),
    (0xF0A5B9D5, 0x82B2C1FB),
    (0x06064CF3, 0xFA51A3DA),
    (0xDA79FA60, 0x207CC464),
    (0xBED20560, 0x3C3C74F3),
    (0x89F9C9F8, 0xD2D14B61),
    (0x35FA38C6, 0xBB04A2C1),
    (0xCB49E3C6, 0xC5626167),
];

fn sigma0(x: u32) -> u32 {
    x.rotate_right(7) ^ x.rotate_right(18) ^ (x >> 3)
}

fn sigma1(x: u32) -> u32 {
    x.rotate_right(17) ^ x.rotate_right(19) ^ (x >> 10)
}

fn expand(words: &mut [u32; 64], first: usize) {
    for i in first..64 {
        words[i] = sigma1(words[i - 2])
            .wrapping_add(words[i - 7])
            .wrapping_add(sigma0(words[i - 15]))
            .wrapping_add(words[i - 16]);
    }
}

fn rounds(state: [u32; 8], words: &[u32; 64], first: usize) -> [u32; 8] {
    let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
    for i in first..64 {
        let constant = if first == 14 && i == 14 {
            ADJUSTMENT
        } else {
            K[i]
        };
        let t1 = h
            .wrapping_add(e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25))
            .wrapping_add(g ^ (e & (f ^ g)))
            .wrapping_add(constant)
            .wrapping_add(words[i]);
        let t2 = (a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22))
            .wrapping_add((a & b) | (c & (a | b)));
        [a, b, c, d, e, f, g, h] = [t1.wrapping_add(t2), a, b, c, d.wrapping_add(t1), e, f, g];
    }
    [a, b, c, d, e, f, g, h]
}

fn initial_state(data: &[u8]) -> [u32; 8] {
    let mut words = [0u32; 64];
    words[14] = u32::from_be_bytes([0, data[0], data[1], data[2]]);
    words[15] = u32::from_be_bytes(data[3..7].try_into().unwrap());
    for i in 16..30 {
        let s1 = sigma1(words[i - 2]) ^ if i == 16 { 0x000B92C0 } else { 0 };
        let mut value = SCHEDULE[i - 16].wrapping_add(s1);
        if i >= 21 {
            value = value.wrapping_add(words[i - 7]);
        }
        if i >= 29 {
            value = value.wrapping_add(sigma0(words[i - 15]) ^ 0x059C0B80);
        }
        words[i] = value;
    }
    words[30] = sigma1(words[28])
        .wrapping_add(words[23])
        .wrapping_add(sigma0(words[15]))
        .wrapping_add(words[14])
        .wrapping_add(ADJUSTMENT)
        .wrapping_sub(K[14]);
    expand(&mut words, 31);
    let working = rounds(RESUME_STATE, &words, 14);
    std::array::from_fn(|i| INITIAL[i].wrapping_add(working[i]))
}

fn sha256_digest(data: &[u8]) -> [u8; 32] {
    assert!(data.len() >= 7, "GEC v2 salt needs at least seven bytes");
    let length = 57 + data.len();
    let mut padded = data[7..].to_vec();
    padded.push(0x80);
    padded.resize(padded.len() + (55 + 64 - length % 64) % 64, 0);
    padded.extend_from_slice(&((length as u64) * 8).to_be_bytes());
    let mut state = initial_state(data);
    for block in padded.chunks_exact(64) {
        let mut words = [0u32; 64];
        for (word, bytes) in words.iter_mut().zip(block.chunks_exact(4)) {
            *word = u32::from_be_bytes(bytes.try_into().unwrap());
        }
        expand(&mut words, 16);
        let working = rounds(state, &words, 0);
        state = std::array::from_fn(|i| state[i].wrapping_add(working[i]));
    }
    let mut digest = [0u8; 32];
    for (chunk, value) in digest.chunks_exact_mut(4).zip(state) {
        chunk.copy_from_slice(&value.to_be_bytes());
    }
    digest
}

fn cs64_digest(data: &[u8], digest: &[u8; 32]) -> [u8; 8] {
    let key_a = u32::from_le_bytes(digest[..4].try_into().unwrap()) | 1;
    let key_b = u32::from_le_bytes(digest[4..8].try_into().unwrap()) | 1;
    let keys = [key_a, key_b];
    let factors = [
        key_a.wrapping_mul(0x82893933),
        key_b.wrapping_mul(0x82893933),
    ];
    let mut terms: Vec<u32> = COEFFICIENTS
        .iter()
        .enumerate()
        .map(|(i, &(coefficient, _))| coefficient.wrapping_mul(factors[i % 2]))
        .collect();
    let mut offsets: Vec<u32> = COEFFICIENTS.iter().map(|&(_, offset)| offset).collect();
    let mut padded = vec![0];
    padded.extend_from_slice(data);
    padded.resize((padded.len() + 7) / 8 * 8, 0);
    for (i, bytes) in padded.chunks_exact(4).enumerate() {
        let word = u32::from_le_bytes(bytes.try_into().unwrap());
        let mut term = word.wrapping_mul(keys[i % 2]);
        let mut offset =
            word.rotate_left(16)
                .wrapping_mul(if i % 2 == 0 { 0xEF0569FB } else { 0xC31713DB });
        if i == 0 {
            term = term.wrapping_add(0xF2F90B1Au32.wrapping_mul(factors[0]));
            offset = offset.wrapping_add(0x0B1A0000);
        }
        terms.push(term);
        offsets.push(offset);
    }
    let (mut swap_acc, mut swap_last, mut state, mut acc) = (0u32, 0u32, 0u32, 0u32);
    for i in (0..terms.len()).step_by(2) {
        let (x, y) = (terms[i], terms[i + 1]);
        let q = offsets[i]
            .wrapping_add(x)
            .rotate_left(16)
            .wrapping_mul(0x76F50F34);
        swap_acc =
            swap_acc.wrapping_add(q.rotate_left(16).wrapping_mul(0xC3EFEA97).wrapping_add(q));
        let q = offsets[i + 1]
            .wrapping_add(y)
            .rotate_left(16)
            .wrapping_mul(0x1881CE3C);
        swap_last = q.rotate_left(16).wrapping_mul(0x35BD1EC9).wrapping_add(q);
        swap_acc = swap_acc.wrapping_add(swap_last);
        state = state.wrapping_mul(key_a).wrapping_add(x);
        for factor in [0xCF98B111, 0x87085B9F, 0x12CEB96D, 0x257E1D83] {
            state = state.rotate_left(16).wrapping_mul(factor);
        }
        acc = acc.wrapping_add(state);
        let mut t = state.wrapping_mul(key_b).wrapping_add(y);
        for factor in [0xA27416F5, 0xD38396FF, 0x7C932B89, 0xBFA49F69] {
            t = t.rotate_left(16).wrapping_mul(factor);
        }
        state = t;
        acc = acc.wrapping_add(state);
    }
    let mut output = [0u8; 8];
    output[..4].copy_from_slice(&(swap_last ^ state).to_le_bytes());
    output[4..].copy_from_slice(&(swap_acc ^ acc).to_le_bytes());
    output
}

fn hex(data: &[u8]) -> String {
    data.iter().map(|byte| format!("{byte:02X}")).collect()
}

pub fn generate(unix_seconds: u64, trusted_client_token: &str) -> String {
    let windows_seconds = u128::from(unix_seconds) + 11_644_473_600;
    let ticks = (windows_seconds - windows_seconds % 300) * 10_000_000;
    let data = format!("{ticks}{trusted_client_token}");
    let digest = sha256_digest(data.as_bytes());
    format!(
        "{}-{}",
        hex(&cs64_digest(data.as_bytes(), &digest)),
        hex(&digest)
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    const TRUSTED: &str = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";

    #[test]
    fn matches_independent_upstream_timestamp_vectors() {
        let mut count = 0;
        for line in include_str!("../tests/fixtures/gec-v2-vectors.tsv")
            .lines()
            .filter(|line| !line.starts_with('#'))
        {
            let (timestamp, expected) = line.split_once('\t').unwrap();
            assert_eq!(
                generate(timestamp.parse().unwrap(), TRUSTED),
                expected,
                "timestamp={timestamp}"
            );
            count += 1;
        }
        assert_eq!(count, 17);
    }

    #[test]
    fn matches_upstream_sha_and_cs64_for_padding_and_word_boundaries() {
        let mut count = 0;
        for line in include_str!("../tests/fixtures/gec-v2-digests.tsv")
            .lines()
            .filter(|line| !line.starts_with('#'))
        {
            let columns: Vec<&str> = line.split('\t').collect();
            let data: Vec<u8> = columns[0]
                .as_bytes()
                .chunks_exact(2)
                .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
                .collect();
            let digest = sha256_digest(&data);
            assert_eq!(hex(&digest), columns[2], "SHA length={}", data.len());
            assert_eq!(
                hex(&cs64_digest(&data, &digest)),
                columns[1],
                "CS64 length={}",
                data.len()
            );
            count += 1;
        }
        assert_eq!(count, 12);
    }

    #[test]
    fn token_uses_five_minute_windows_and_uppercase_v2_shape() {
        let token = generate(1793318400, TRUSTED);
        assert_eq!(token, generate(1793318699, TRUSTED));
        assert_ne!(token, generate(1793318700, TRUSTED));
        let (cs64, digest) = token.split_once('-').unwrap();
        assert_eq!((cs64.len(), digest.len()), (16, 64));
        assert!(cs64
            .chars()
            .chain(digest.chars())
            .all(|c| c.is_ascii_digit() || ('A'..='F').contains(&c)));
    }
}
