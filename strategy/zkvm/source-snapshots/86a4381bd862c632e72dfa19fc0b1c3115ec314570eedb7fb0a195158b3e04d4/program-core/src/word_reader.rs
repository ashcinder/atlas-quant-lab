//! Same SDK word protocol; read u32 directly from the existing buffered bytes.
use risc0_zkvm::serde::{Error, Result, WordRead};
use std::io::{BufRead, BufReader, Read};

pub struct WordReader<R: Read> { input: BufReader<R> }

impl<R: Read> WordReader<R> {
    pub fn new(input: R) -> Self { Self { input: BufReader::with_capacity(8192, input) } }
}

impl<R: Read> WordRead for WordReader<R> {
    fn read_words(&mut self, words: &mut [u32]) -> Result<()> {
        for word in words {
            let bytes = self.input.fill_buf().map_err(|_| Error::DeserializeUnexpectedEnd)?;
            if bytes.len() >= 4 {
                *word = u32::from_le_bytes(bytes[..4].try_into().unwrap());
                self.input.consume(4);
            } else {
                // Generic readers can return short reads or split a word.
                let mut bytes = [0u8; 4];
                self.input.read_exact(&mut bytes).map_err(|_| Error::DeserializeUnexpectedEnd)?;
                *word = u32::from_le_bytes(bytes);
            }
        }
        Ok(())
    }

    fn read_padded_bytes(&mut self, bytes: &mut [u8]) -> Result<()> {
        self.input.read_exact(bytes).map_err(|_| Error::DeserializeUnexpectedEnd)?;
        let padding = (4 - bytes.len() % 4) % 4;
        let mut discarded = [0u8; 3];
        self.input.read_exact(&mut discarded[..padding]).map_err(|_| Error::DeserializeUnexpectedEnd)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    struct Chunked { input: Cursor<Vec<u8>>, maximum: usize }
    impl Read for Chunked {
        fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
            let size = bytes.len().min(self.maximum);
            self.input.read(&mut bytes[..size])
        }
    }

    #[test]
    fn sdk_serde_and_padding_match_across_short_reads_and_buffer_boundaries() {
        let value = ("行情\0x".to_owned(), (0..10000).map(|i| i as i64 * -123456789).collect::<Vec<_>>());
        let words = risc0_zkvm::serde::to_vec(&value).unwrap();
        let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
        for maximum in [1, 2, 3, 4, 7, 8191, 8192, 8193, 16384] {
            let input = Chunked { input: Cursor::new(bytes.clone()), maximum };
            let actual: (String, Vec<i64>) = serde::Deserialize::deserialize(
                &mut risc0_zkvm::serde::Deserializer::new(WordReader::new(input))).unwrap();
            assert_eq!(actual, value);
        }
        for length in [0, 1, 3, 4, 5, 8191, 8192, 8193, bytes.len()-1, bytes.len()-4] {
            let input = WordReader::new(Cursor::new(bytes[..length].to_vec()));
            let result: Result<(String, Vec<i64>)> = serde::Deserialize::deserialize(
                &mut risc0_zkvm::serde::Deserializer::new(input));
            assert!(matches!(result, Err(Error::DeserializeUnexpectedEnd)));
        }
    }

    #[test]
    fn every_padding_byte_is_required_but_not_interpreted() {
        for size in 0usize..=9 {
            let padded = size.div_ceil(4) * 4;
            let mut input = WordReader::new(Cursor::new(vec![0xa5; padded]));
            input.read_padded_bytes(&mut vec![0; size]).unwrap();
            if padded > 0 {
                let mut input = WordReader::new(Cursor::new(vec![0xa5; padded-1]));
                assert!(input.read_padded_bytes(&mut vec![0; size]).is_err());
            }
        }
    }
}
