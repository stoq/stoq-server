var http = require('http'),
    Stream = require('stream').Transform,
    bsplit = require('./buffer-split');

function Snapshooter(options, onFrame) {
  this.options = options;
  this.frame = null;
  this.onFrame = onFrame || function() {};

  this.connect();
}

Snapshooter.prototype.connect = function() {
  console.log('connecting to ' + this.options);
  var tryAgain = function() {
    console.log('could not connect to ' + this.options + ' trying again in 5 seconds');
    setTimeout(this.connect.bind(this), 5000);
  }.bind(this);

  var request = http.request(this.options, function (response) {
    var boundary = '--' + response.headers['content-type'].replace(/^.*boundary=/, '');
    var frame = new Stream();

    response.on('data', function(chunk) {
      // Try to find the exact frame, separated by the boundary tag
      frame.push(chunk);
      var buffer = frame.read();
      var split = bsplit(buffer, boundary);

      if (split.length > 1) {
        // Once a full frame has been loaded, assign the JPEG image to 'frame'
        this.frame = bsplit(split[0], '\r\n\r\n', 1)[1];
        this.onFrame(this.frame);

        // And then start accumulating the next frame
        return frame.push(split[split.length - 1]);
      }

      frame.push(buffer);
    }.bind(this));

    // Do not let the MJPEG stream end, if it ended, try connecting again
    response.on('end', tryAgain);
  }.bind(this));

  request.on('socket', function(socket) {
    // If we have 3 seconds of innactivity, try again
    socket.setTimeout(3000, function() {
      // This will trigger response.on('end') on the http.request
      request.abort();
    });
  });

  request.on('error', tryAgain);

  request.end();
};

module.exports = Snapshooter;
