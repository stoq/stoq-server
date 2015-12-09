var io = require('socket.io-client'),
    MultiRTC = require('./node_modules/components/utils/multi-rtc');

var socket;
var clients = new MultiRTC({wrtc: require('wrtc')});

/*
 * Socket.IO Hooks
 */

var connect = function() {
  console.info('trying to connect to ws://localhost:5000');
  socket = io.connect('ws://localhost:5000', {
    'force new connection': true,
    'max reconnection attempts': Infinity,
  });

  clients.signaller = socket;

  socket.on('connect', function() {
    console.info('connected to the signal server');
    socket.emit('join', '6a35c58a-d8a1-44d5-9141-fc5c3764d13c');
  });

  socket.on('joined', function(id) {
    clients.add(id);
  });

  socket.on('signal', function(data) {
    clients.add(data.source, data.signal);
  });

  socket.on('disconnect', function() {
    console.info('disconnected to the signal server');
  });

  // Verifies if an error occurs when try to connect with the server. If the
  // server is off, retry the connection in 5 seconds (try until the server
  // stays online)
  socket.on('error', function(error) {
    if (error.match(/ECONNREFUSED/)) {
      console.error('connection failed: trying again in 5 seconds');
      setTimeout(connect, 5000);
    }
  });
};

connect();

/*
 * WebRTC Hooks
 */

clients.on('connect', function(id) {
  console.log('connected to peer', id);
});

clients.on('data', function(id, data) {
  console.log(id, 'sent', data);
});

clients.on('disconnect', function(id) {
  console.log('disconnected to peer', id);
})

// Send a message passed from console/terminal peer-to-peer
var stdin = process.openStdin();
stdin.addListener('data', function(data) {
  clients.send(data.toString());
});
