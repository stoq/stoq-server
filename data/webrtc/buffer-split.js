var bufferIndexOf = require('buffer-indexof');

/** Splits a buffer like String.prototype.split
 *
 * @param {Buffer} buffer The buffer to be split
 * @param {Buffer|String} delim The delimiter used to split
 * @param {Integer} max the maximum number of splites to be performed
 */

module.exports = function(buffer, delim, max) {
  max = max || Infinity;

  if (typeof delim === 'string') {
    delim = new Buffer(delim);
  }

  var count = 0,
      search = -1,
      splits = [];

  while ((search = bufferIndexOf(buffer, delim)) > -1) {
    // Add the buffer slice to the return list
    splits.push(buffer.slice(0, search));

    // Pad the buffer with the already found slices
    buffer = buffer.slice(search + delim.length, buffer.length);

    if (count++ == max) {
      break;
    }
  }

  if (buffer.length) {
    splits.push(buffer);
  }

  return splits;
}
