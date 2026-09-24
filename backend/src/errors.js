'use strict';

// 요청 값이 잘못된 경우 (HTTP 400)
class InputError extends Error {
  constructor(message, code = 'INVALID_INPUT', status = 400) {
    super(message);
    this.name = 'InputError';
    this.code = code;
    this.status = status;
  }
}

module.exports = { InputError };
