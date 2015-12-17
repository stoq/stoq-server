var io = require('socket.io-client'),
    xmlrpc = require('xmlrpc'),
    MultiRTC = require('./node_modules/components/utils/multi-rtc');

var socket;
var stoqServer = xmlrpc.createClient({host: 'localhost', port: 6970, path: '/XMLRPC'});
var clients = new MultiRTC({wrtc: require('wrtc')});
var host = process.env.STOQ_API_HOST || 'http://api.stoq.com.br';

/*
 * Socket.IO Hooks
 */

var connect = function() {
  console.info('trying to connect to ', host);
  socket = io.connect(host, {
    'force new connection': true,
    'max reconnection attempts': Infinity,
  });

  clients.signaller = socket;

  socket.on('connect', function() {
    console.info('connected to the signal server');
    stoqServer.methodCall('htsql_query', ["/parameter_data.filter(field_name = 'USER_HASH').field_value"],
      function(err, result) {
        var hash = JSON.parse(result).field_value[0];
        // Properly format the UUID
        hash = hash.slice(0, 8) + '-' + hash.slice(8, 12) + '-' +
               hash.slice(12, 16) + '-' + hash.slice(16, 20) + '-' +
               hash.slice(20);
        clients.hash = hash;

        socket.emit('join', hash)
    });
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

var events = {
  who: function() {
    return clients.send({
      type: 'whoami',
      hash: clients.hash,
    }, id);
  },

  onHTSQLQuery: function(id, data) {
    stoqServer.methodCall('htsql_query', [data.htsql], function(err, result) {
      err || clients.send({
        type: 'htsql',
        result: JSON.parse(result),
      }, id);
    });
  },
};

clients.on('connect', function(id) {
  console.log('connected to peer', id);
});

clients.on('data', function(id, data) {
  try {
    events[data.type](id, data);
  }
  catch(err) {
    console.error('Error: ', err);
    clients.send({
      type: 'error',
      error: err.toString(),
    });
  }
});

clients.on('disconnect', function(id) {
  console.log('disconnected to peer', id);
});
