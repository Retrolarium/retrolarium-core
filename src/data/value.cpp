#include <retrolarium/core/value.hpp>

namespace retrolarium::core {
namespace {

[[noreturn]] void wrongKind(const char *wanted)
{
    throw ValueError(std::string("value is not ") + wanted);
}

} // namespace

Value Value::boolean(bool value)
{
    Value result;
    result.kind_ = Kind::Boolean;
    result.boolean_ = value;
    return result;
}

Value Value::integer(std::int64_t value)
{
    Value result;
    result.kind_ = Kind::Integer;
    result.integer_ = value;
    return result;
}

Value Value::real(double value)
{
    Value result;
    result.kind_ = Kind::Double;
    result.real_ = value;
    return result;
}

Value Value::string(std::string value)
{
    Value result;
    result.kind_ = Kind::String;
    result.string_ = std::move(value);
    return result;
}

Value Value::array(std::vector<Value> value)
{
    Value result;
    result.kind_ = Kind::Array;
    result.array_ = std::move(value);
    return result;
}

Value Value::object(std::map<std::string, Value> value)
{
    Value result;
    result.kind_ = Kind::Object;
    result.object_ = std::move(value);
    return result;
}

bool Value::asBoolean() const
{
    if (kind_ != Kind::Boolean) wrongKind("a boolean");
    return boolean_;
}

std::int64_t Value::asInteger() const
{
    if (kind_ != Kind::Integer) wrongKind("an integer");
    return integer_;
}

double Value::asDouble() const
{
    // An integer is a valid double; the reverse is not, so only this direction
    // is widened.
    if (kind_ == Kind::Integer) return static_cast<double>(integer_);
    if (kind_ != Kind::Double) wrongKind("a number");
    return real_;
}

const std::string &Value::asString() const
{
    if (kind_ != Kind::String) wrongKind("a string");
    return string_;
}

const std::vector<Value> &Value::asArray() const
{
    if (kind_ != Kind::Array) wrongKind("an array");
    return array_;
}

const std::map<std::string, Value> &Value::asObject() const
{
    if (kind_ != Kind::Object) wrongKind("an object");
    return object_;
}

const Value *Value::find(const std::string &name) const
{
    if (kind_ != Kind::Object) return nullptr;
    const auto found = object_.find(name);
    return found == object_.end() ? nullptr : &found->second;
}

bool Value::operator==(const Value &other) const
{
    if (kind_ != other.kind_) return false;
    switch (kind_) {
    case Kind::Null:
        return true;
    case Kind::Boolean:
        return boolean_ == other.boolean_;
    case Kind::Integer:
        return integer_ == other.integer_;
    case Kind::Double:
        return real_ == other.real_;
    case Kind::String:
        return string_ == other.string_;
    case Kind::Array:
        return array_ == other.array_;
    case Kind::Object:
        return object_ == other.object_;
    }
    return false;
}

} // namespace retrolarium::core
